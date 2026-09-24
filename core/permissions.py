# core/permissions.py

STATUS_PERMISSIONS: dict[int, int] = {
    1: 1,
    2: 10,
    3: 100,
    4: 1000,
}

# Yazma icazəsi olan dəyərlər (create / update / delete)
WRITE_PERMISSION_VALUES = (1, 10, 100)


def get_permission_value(status_id: int) -> int:
    """Status ID-yə uyğun icazə dəyərini qaytarır. Naməlum status → 0."""
    return STATUS_PERMISSIONS.get(status_id, 0)
