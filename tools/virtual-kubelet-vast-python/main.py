#!/usr/bin/env python3
# ... previous imports and setup remain unchanged ...

class VastAIClient:
    # ... __init__, __aenter__, __aexit__, test_connection, search_offers remain unchanged ...

    async def buy_instance(self, ask_id: int, image: str = "ubuntu:22.04", disk: float = 50.0, ssh_key: str = None) -> Optional[Dict]:
        """Buy/create an instance from a Vast.ai ask/offer using correct accept endpoint.
        Tries POST /asks/{ask_id}/accept/ first, then falls back to /asks/{ask_id}/accept.
        """
        if not self.session:
            raise RuntimeError("Client session not initialized")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"image": image, "disk": disk}
        if ssh_key:
            payload["ssh_key"] = ssh_key

        paths = [f"/asks/{ask_id}/accept/", f"/asks/{ask_id}/accept"]
        for path in paths:
            try:
                async with self.session.post(f"{self.base_url}{path}", headers=headers, json=payload) as resp:
                    txt = await resp.text()
                    if resp.status in (200, 201):
                        try:
                            data = await resp.json()
                        except Exception:
                            # Some endpoints may return plain text id
                            data = {"new_contract": int(txt.strip()) if txt.strip().isdigit() else txt}
                        logger.info("Instance creation initiated", ask_id=ask_id, instance_id=data.get("new_contract"), endpoint=path)
                        return data
                    else:
                        logger.error("buy_instance failed", ask_id=ask_id, status_code=resp.status, response=txt, endpoint=path)
            except Exception as e:
                logger.error("buy_instance exception", ask_id=ask_id, error=str(e), endpoint=path)
        return None

    # get_instance, list_instances, delete_instance, poll_instance_ready remain unchanged

# Add a simple concurrency limiter for instance creation
INSTANCE_BUY_SEMAPHORE = asyncio.Semaphore(int(os.getenv("VK_MAX_BUY_CONCURRENCY", "2")))

class VirtualKubelet:
    # ... init and other methods remain unchanged ...

    async def create_pod(self, pod: V1Pod):
        pod_name = pod.metadata.name
        logger.info("Creating pod on Vast.ai", pod_name=pod_name)
        try:
            gpu_list, price_max, region = self._parse_annotations(pod)
            async with VastAIClient(self.api_key) as vast:
                offer = await self._find_offer(vast, gpu_list, price_max, region)
                if not offer:
                    logger.error("No matching Vast.ai offers after fallback", pod_name=pod_name, requested=gpu_list, price_max=price_max, region=region)
                    await self.update_pod_status_failed(pod, "No GPU instances available")
                    return

                logger.info("Selected Vast.ai offer", pod_name=pod_name, gpu=offer.get("gpu_name"), price=offer.get("dph_total"), location=offer.get("geolocation"), offer_id=offer.get("id"))

                # Limit concurrent buys to avoid floods
                async with INSTANCE_BUY_SEMAPHORE:
                    buy_result = await vast.buy_instance(offer["id"], image="ubuntu:22.04", disk=50.0)

                if not buy_result:
                    logger.error("Failed to buy Vast.ai instance", pod_name=pod_name, offer_id=offer.get("id"))
                    await self.update_pod_status_failed(pod, "Failed to create instance")
                    return

                instance_id = buy_result.get("new_contract") if isinstance(buy_result, dict) else buy_result
                if not instance_id:
                    logger.error("No instance ID returned from accept", pod_name=pod_name, buy_result=buy_result)
                    await self.update_pod_status_failed(pod, "Invalid instance creation response")
                    return

                logger.info("Instance creation started", pod_name=pod_name, instance_id=instance_id)

                ready_instance = await vast.poll_instance_ready(int(instance_id), timeout_seconds=300)
                if not ready_instance:
                    logger.error("Instance failed to become ready", pod_name=pod_name, instance_id=instance_id)
                    await vast.delete_instance(int(instance_id))
                    await self.update_pod_status_failed(pod, "Instance failed to start")
                    return

                instance = {
                    "id": int(instance_id),
                    "status": "running",
                    "public_ip": ready_instance.get("public_ipaddr"),
                    "ssh_port": ready_instance.get("ssh_port"),
                    "offer": offer,
                    "instance_data": ready_instance
                }
                self.pod_instances[pod_name] = instance

                logger.info("Instance ready and assigned", pod_name=pod_name, instance_id=instance["id"], public_ip=instance["public_ip"], ssh_port=instance["ssh_port"])
                await self.update_pod_status_running(pod, instance)

        except Exception as e:
            logger.error("Error creating pod", pod_name=pod_name, error=str(e))
            await self.update_pod_status_failed(pod, str(e))
