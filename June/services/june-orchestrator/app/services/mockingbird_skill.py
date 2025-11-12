# ... previous code unchanged ...
            # Connect to room
            await room.connect(
                self.livekit_url,
                jwt,
                options=rtc.RoomOptions(auto_subscribe=False)  # Manual subscription
            )
            
            logger.info(f"✅ Connected to room '{room_name}' as recorder")
            await asyncio.sleep(0.5)

            # DEBUG: Log all room attributes and dict
            logger.info(f"DEBUG room attributes: {dir(room)}")
            try:
                logger.info(f"DEBUG room.__dict__: {room.__dict__}")
            except Exception as e:
                logger.warning(f"DEBUG: could not print room.__dict__: {e}")

            # Try candidates and print if present
            candidates = ["remote_participants", "participants", "_remote_participants", "remoteParticipants"]
            for attr in candidates:
                exists = hasattr(room, attr)
                val = getattr(room, attr, None)
                logger.info(f"DEBUG: room has {attr}: {exists}, type={type(val)}, value={val}")

            # Try old property for compatibility and log gracefully if issue
            try:
                existing_participants = list(room.remote_participants.values())
                logger.info(f"👥 Found {len(existing_participants)} existing participants (room.remote_participants)")
            except Exception as e:
                logger.error(f"❌ Error accessing room.remote_participants: {e}")
                existing_participants = []

            for participant in existing_participants:
                logger.info(f"  - {getattr(participant, 'identity', 'N/A')}")
                if getattr(participant, "identity", None) == target_identity:
                    logger.info(f"✅ Found target participant already in room!")
                    await self._subscribe_to_participant(participant)
                    break
            else:
                logger.info(f"🔎 Target participant not in room yet, waiting for events...")

            # ... remainder unchanged ...
