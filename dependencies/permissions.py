# dependencies/permissions.py
from typing import Annotated

from fastapi import Depends, HTTPException, status

from core.permissions import WRITE_PERMISSION_VALUES, get_permission_value
from dependencies.auth import get_current_user
from models.user_model import UserModel

# Arşivdeki yanlış girilmiş tamir notlarını yalnızca bu hesap düzeltebilir.
# Kural iki koşulun birlikte sağlanmasını ister: e-posta eşleşmesi + Manager
# (``status_id = 2``) yetkisi. E-posta karşılaştırması büyük/küçük harf ve
# boşluklardan bağımsızdır.
ARCHIVE_NOTE_EDITOR_EMAIL = "fyildiz@ustay.com"
ARCHIVE_NOTE_EDITOR_STATUS_ID = 2


async def require_write_permission(
    current_user: Annotated[UserModel, Depends(get_current_user)],
) -> UserModel:
    """
    Create / Update / Delete üçün.
    Status 1, 2, 3 (dəyər 1, 10, 100) icazəlidir.
    Status 4 (dəyər 1000) yalnız oxuya bilər → 403.
    """
    value = get_permission_value(current_user.status_id)

    if value not in WRITE_PERMISSION_VALUES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için izniniz yok",
        )

    return current_user


async def require_archive_note_permission(
    current_user: Annotated[UserModel, Depends(get_current_user)],
) -> UserModel:
    """Arşiv notu düzenleme yetkisi.

    Tamir arşivindeki notlar geçmişe dönük bir kayıt olduğu için yalnızca
    ``fyildiz@ustay.com`` hesabı (Manager / ``status_id = 2``) düzeltebilir.
    Diğer kullanıcılar 403 alır; kural frontend'de de aynı sabitlerle
    uygulanır (``utils/repair.js`` → ``canEditArchiveNotes``).
    """
    email = (current_user.email or "").strip().lower()

    if (
        email != ARCHIVE_NOTE_EDITOR_EMAIL
        or current_user.status_id != ARCHIVE_NOTE_EDITOR_STATUS_ID
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Arşiv notlarını yalnızca yetkili kullanıcı düzeltebilir",
        )

    return current_user
