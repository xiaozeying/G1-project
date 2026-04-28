from __future__ import annotations

from datetime import timedelta

import aiohttp
from livekit.api import (
    AccessToken,
    CreateAgentDispatchRequest,
    CreateRoomRequest,
    ListRoomsRequest,
    ListParticipantsRequest,
    LiveKitAPI,
    VideoGrants,
)

from src.settings import AppSettings


def livekit_api_url(ws_url: str) -> str:
    if ws_url.startswith("ws://"):
        return "http://" + ws_url[len("ws://") :]
    if ws_url.startswith("wss://"):
        return "https://" + ws_url[len("wss://") :]
    return ws_url


def build_room_token(settings: AppSettings, room_name: str, identity: str) -> str:
    grants = VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    return (
        AccessToken(settings.livekit.api_key, settings.livekit.api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_ttl(timedelta(minutes=settings.web.token_ttl_minutes))
        .with_grants(grants)
        .to_jwt()
    )


async def ensure_room_ready(
    settings: AppSettings,
    room_name: str,
    *,
    create_room: bool,
    dispatch_agent: bool,
    dispatch_metadata: str,
    replace_existing_dispatch: bool = False,
) -> None:
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
        async with LiveKitAPI(
            url=livekit_api_url(settings.livekit.url),
            api_key=settings.livekit.api_key,
            api_secret=settings.livekit.api_secret,
            session=session,
            timeout=timeout,
        ) as lkapi:
            if create_room:
                rooms = await lkapi.room.list_rooms(ListRoomsRequest(names=[room_name]))
                if not getattr(rooms, "rooms", None):
                    await lkapi.room.create_room(
                        CreateRoomRequest(
                            name=room_name,
                            empty_timeout=60 * 10,
                            max_participants=8,
                        )
                    )

            if not dispatch_agent:
                return

            dispatches = await lkapi.agent_dispatch.list_dispatch(room_name)
            matching_dispatch_exists = False
            for dispatch in dispatches:
                if getattr(dispatch, "agent_name", "") != settings.agent.name:
                    continue
                matching_dispatch_exists = True
                if not replace_existing_dispatch:
                    break

            if matching_dispatch_exists and not replace_existing_dispatch:
                return

            if matching_dispatch_exists and replace_existing_dispatch:
                for dispatch in dispatches:
                    if getattr(dispatch, "agent_name", "") != settings.agent.name:
                        continue
                    dispatch_id = getattr(dispatch, "id", "")
                    if dispatch_id:
                        await lkapi.agent_dispatch.delete_dispatch(dispatch_id, room_name)

            await lkapi.agent_dispatch.create_dispatch(
                CreateAgentDispatchRequest(
                    room=room_name,
                    agent_name=settings.agent.name,
                    metadata=dispatch_metadata,
                )
            )


async def list_room_participants(
    settings: AppSettings,
    room_name: str,
) -> list[object]:
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
        async with LiveKitAPI(
            url=livekit_api_url(settings.livekit.url),
            api_key=settings.livekit.api_key,
            api_secret=settings.livekit.api_secret,
            session=session,
            timeout=timeout,
        ) as lkapi:
            response = await lkapi.room.list_participants(
                ListParticipantsRequest(room=room_name)
            )
            return list(getattr(response, "participants", []) or [])
