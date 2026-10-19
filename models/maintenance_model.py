# models/maintenance_model.py
"""Periodic maintenance planning and history models.

A machine has at most one maintenance setting (the plan). Completed
maintenance events and counter readings are kept in ``maintenance_records`` so
that the plan can be recalculated and audited.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class MachineMaintenanceSettingModel(Base):
    __tablename__ = "machine_maintenance_settings"

    __table_args__ = (
        CheckConstraint(
            "usage_unit IN ('km', 'hour')",
            name="ck_machine_maintenance_settings_usage_unit",
        ),
        CheckConstraint(
            "interval_value > 0",
            name="ck_machine_maintenance_settings_interval_positive",
        ),
        CheckConstraint(
            "last_counter IS NULL OR last_counter >= 0",
            name="ck_machine_maintenance_settings_last_counter_non_negative",
        ),
        CheckConstraint(
            "current_counter IS NULL OR current_counter >= 0",
            name="ck_machine_maintenance_settings_current_counter_non_negative",
        ),
        CheckConstraint(
            "warning_threshold IS NULL OR warning_threshold >= 0",
            name="ck_machine_maintenance_settings_warning_threshold_non_negative",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # "km" for odometer based machines, "hour" for hour-meter based machines.
    usage_unit = Column(String(20), nullable=False)

    # Maintenance interval in the chosen unit (e.g. every 10.000 km / 500 h).
    interval_value = Column(Float, nullable=False)

    # Counter value and date of the last completed maintenance.
    last_counter = Column(Float, nullable=True)
    last_maintenance_date = Column(Date, nullable=True)

    # Latest known counter reading.
    current_counter = Column(Float, nullable=True)
    current_counter_date = Column(Date, nullable=True)

    # Optional override. When NULL the API uses 10% of ``interval_value``.
    warning_threshold = Column(Float, nullable=True)

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    machine = relationship("AllMachineModel", back_populates="maintenance_setting")


class MaintenanceRecordModel(Base):
    __tablename__ = "maintenance_records"

    __table_args__ = (
        CheckConstraint(
            "record_type IN ('reading', 'maintenance')",
            name="ck_maintenance_records_record_type",
        ),
        CheckConstraint(
            "counter_value IS NULL OR counter_value >= 0",
            name="ck_maintenance_records_counter_non_negative",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # "reading" = counter update, "maintenance" = completed maintenance.
    record_type = Column(
        String(20),
        nullable=False,
        default="maintenance",
        server_default="maintenance",
    )

    record_date = Column(Date, nullable=False)
    counter_value = Column(Float, nullable=True)

    # Snapshots so history remains readable if the plan is edited later.
    usage_unit = Column(String(20), nullable=True)
    interval_value = Column(Float, nullable=True)

    notes = Column(Text, nullable=True)

    created_by_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    machine = relationship("AllMachineModel", back_populates="maintenance_records")
    created_by = relationship("UserModel")


__all__ = [
    "MachineMaintenanceSettingModel",
    "MaintenanceRecordModel",
]
