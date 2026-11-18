# repositories/meter_log_lookup.py
"""Shared SQL helper for the newest KM / engine-hour reading per machine.

Several forms (new repair, new tire) show the selected machine's latest meter
snapshot.  Keeping the window query here means they all agree with the **Güncel
KM ve Motor Saatleri** page on which row is "the latest": the newest
``log_date``, then the newest save time, then the highest id.
"""

from sqlalchemy import func, select

from models.meter_log_model import MachineMeterLogModel


def latest_meter_log_subquery():
    """Return a subquery with one row per machine (``row_number == 1``)."""

    row_number = func.row_number().over(
        partition_by=MachineMeterLogModel.machine_id,
        order_by=[
            MachineMeterLogModel.log_date.desc(),
            MachineMeterLogModel.created_at.desc(),
            MachineMeterLogModel.id.desc(),
        ],
    ).label("row_number")

    return select(
        MachineMeterLogModel.machine_id.label("machine_id"),
        MachineMeterLogModel.km.label("last_km"),
        MachineMeterLogModel.engine_hours.label("last_engine_hours"),
        MachineMeterLogModel.log_date.label("last_log_date"),
        MachineMeterLogModel.created_at.label("last_logged_at"),
        row_number,
    ).subquery()


__all__ = ["latest_meter_log_subquery"]
