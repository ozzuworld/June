#!/usr/bin/env python3
# Harden instance creation: verify content-type, avoid int() on HTML, better error message
# (imports and other code remain unchanged above)

class VastAIClient:
    # ... other methods unchanged ...
    async def buy_instance(self, ask_id: int, pod_annotations: Dict[str, str]) -> Optional[Dict]:
        if not self.session:
            raise RuntimeError("Client session not initialized")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "image": pod_annotations.get("vast.ai/image", "ubuntu:22.04"),
            "disk": float(pod_annotations.get("vast.ai/disk", "50")),
            "runtype": pod_annotations.get("vast.ai/runtype", "ssh_direct"),
        }
        if "vast.ai/env" in pod_annotations:
            payload["env"] = pod_annotations["vast.ai/env"]
        if "vast.ai/price-max" in pod_annotations:
            payload["price"] = float(pod_annotations["vast.ai/price-max"])
        if "vast.ai/onstart-cmd" in pod_annotations:
            payload["onstart_cmd"] = pod_annotations["vast.ai/onstart-cmd"]
        if "vast.ai/login" in pod_annotations:
            payload["login"] = pod_annotations["vast.ai/login"]
        if "vast.ai/entrypoint" in pod_annotations:
            payload["entrypoint"] = pod_annotations["vast.ai/entrypoint"]

        endpoint = f"/instances/create/{ask_id}/"
        try:
            async with self.session.post(f"{self.base_url}{endpoint}", headers=headers, json=payload) as resp:
                body = await resp.read()
                ctype = resp.headers.get('Content-Type','')
                txt_preview = body.decode(errors='ignore')[:500]
                logger.info("Instance creation request", ask_id=ask_id, endpoint=endpoint, status_code=resp.status, content_type=ctype, body_preview=txt_preview)

                if resp.status not in (200,201):
                    logger.error("buy_instance failed (non-2xx)", ask_id=ask_id, status_code=resp.status, content_type=ctype, response_preview=txt_preview)
                    return None

                data = None
                if 'application/json' in ctype.lower():
                    try:
                        data = await resp.json()
                    except Exception as je:
                        logger.error("Failed to parse JSON create response", error=str(je), response_preview=txt_preview)
                        return None
                else:
                    # Plain text contract id (rare). Require it to be numeric to avoid HTML
                    stripped = txt_preview.strip()
                    if stripped.isdigit():
                        data = {"new_contract": stripped}
                    else:
                        logger.error("Create returned non-JSON non-numeric body", response_preview=txt_preview)
                        return None

                instance_id = data.get("new_contract")
                if not instance_id:
                    logger.error("Create response missing new_contract", data_preview=str(data)[:300])
                    return None

                logger.info("Instance creation initiated", ask_id=ask_id, instance_id=instance_id)
                return data
        except Exception as e:
            logger.error("buy_instance exception", ask_id=ask_id, error=str(e), endpoint=endpoint)
            return None

class VirtualKubelet:
    # ... other methods unchanged ...
    async def create_pod(self, pod: V1Pod):
        pod_name = pod.metadata.name
        logger.info("Creating pod on Vast.ai", pod_name=pod_name)
        try:
            gpu_list, price_max, region = self._parse_annotations(pod)
            async with VastAIClient(self.api_key) as vast:
                offer = await self._find_offer(vast, gpu_list, price_max, region)
                if not offer:
                    await self.update_pod_status_failed(pod, "No GPU instances available")
                    return
                async with INSTANCE_BUY_SEMAPHORE:
                    buy_result = await vast.buy_instance(offer["id"], pod.metadata.annotations or {})
                if not buy_result:
                    await self.update_pod_status_failed(pod, "Failed to create instance (non-JSON or non-2xx)")
                    return
                instance_id = buy_result.get("new_contract")
                if not (isinstance(instance_id, str) and instance_id.isdigit()) and not isinstance(instance_id, int):
                    await self.update_pod_status_failed(pod, "Invalid instance id in response")
                    return
                instance_id_int = int(instance_id)
                ready_instance = await vast.poll_instance_ready(instance_id_int, timeout_seconds=300)
                if not ready_instance:
                    await vast.delete_instance(instance_id_int)
                    await self.update_pod_status_failed(pod, "Instance failed to start")
                    return
                instance = {
                    "id": instance_id_int,
                    "status": "running",
                    "public_ip": ready_instance.get("public_ipaddr"),
                    "ssh_port": ready_instance.get("ssh_port"),
                    "offer": offer,
                    "instance_data": ready_instance
                }
                self.pod_instances[pod_name] = instance
                await self.update_pod_status_running(pod, instance)
        except Exception as e:
            logger.error("Error creating pod", pod_name=pod_name, error=str(e))
            await self.update_pod_status_failed(pod, str(e))
