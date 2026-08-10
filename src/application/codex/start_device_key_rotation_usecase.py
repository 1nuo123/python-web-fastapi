"""Codex 设备公钥轮换登记用例。"""

from __future__ import annotations

from src.application.codex.manage_device_authorization_usecase import (
    CreateDeviceAuthorizationUsecase,
)
from src.application.codex.manage_device_challenge_usecase import (
    VerifyDeviceChallengeUsecase,
)
from src.core.codex_contract.device_authorization_contract import (
    DeviceAuthorizationCreateDetail,
    DeviceAuthorizationEnvelope,
)
from src.core.codex_contract.device_key_contract import DeviceKeyRotationStartDetail


class StartDeviceKeyRotationUsecase:
    """旧 key proof 通过后创建待用户确认的新 key 授权。"""

    def __init__(
        self,
        *,
        challenge_verifier: VerifyDeviceChallengeUsecase,
        authorization_creator: CreateDeviceAuthorizationUsecase,
    ) -> None:
        self._challenge_verifier = challenge_verifier
        self._authorization_creator = authorization_creator

    async def execute(
        self,
        *,
        detail: DeviceKeyRotationStartDetail,
        verification_uri: str,
    ) -> DeviceAuthorizationEnvelope:
        subject = await self._challenge_verifier.verify_identity(proof=detail.proof)
        return await self._authorization_creator.execute(
            detail=DeviceAuthorizationCreateDetail(
                key_id=detail.new_key_id,
                display_name=detail.display_name,
                platform=detail.platform,
                public_key_base64=detail.public_key_base64,
                nonce=detail.nonce,
                nonce_signature_base64=detail.nonce_signature_base64,
            ),
            verification_uri=verification_uri,
            rotation_host_id=subject.host_id,
            rotation_old_key_id=subject.key_id,
            owner_subject_id=subject.owner_subject_id,
        )
