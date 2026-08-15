"""Seed demo missions + flight approvals for the current org/drones.

Run: .venv/bin/python scripts/seed_demo_data.py
(idempotent: skips if missions already exist)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///data/dev.db"
)

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.drone import Drone
from app.models.flight_approval import FlightApproval
from app.models.mission import Mission
from app.models.organization import Organization

NOW = datetime.now(timezone.utc)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        org = (await db.execute(select(Organization))).scalars().first()
        if org is None:
            print("no org found; run seed_drones.py first")
            return
        drones = (await db.execute(select(Drone))).scalars().all()
        if not drones:
            print("no drones found; run seed_drones.py first")
            return

        existing = (await db.execute(select(Mission))).scalars().all()
        if existing:
            print(f"missions already exist ({len(existing)}); skip")
            return

        # --- missions ---
        missions = [
            Mission(
                id=uuid4(),
                org_id=org.id,
                drone_id=drones[0].id,
                name="天府大道巡检 Demo",
                template="waypoint",
                waypoints=[
                    {"lat": 30.5720, "lng": 104.0660, "alt": 100},
                    {"lat": 30.5760, "lng": 104.0700, "alt": 100},
                    {"lat": 30.5800, "lng": 104.0740, "alt": 120},
                ],
                params={"speed": 8, "rtl_on_finish": True},
                status="completed",
                created_at=NOW - timedelta(hours=5),
                dispatched_at=NOW - timedelta(hours=4, minutes=30),
                completed_at=NOW - timedelta(hours=3),
            ),
            Mission(
                id=uuid4(),
                org_id=org.id,
                drone_id=drones[1].id,
                name="锦城湖航拍 Demo",
                template="waypoint",
                waypoints=[
                    {"lat": 30.5740, "lng": 104.0600, "alt": 80},
                    {"lat": 30.5790, "lng": 104.0650, "alt": 80},
                ],
                params={"speed": 6},
                status="in_progress",
                created_at=NOW - timedelta(minutes=40),
                dispatched_at=NOW - timedelta(minutes=25),
            ),
            Mission(
                id=uuid4(),
                org_id=org.id,
                drone_id=drones[2].id,
                name="龙泉山测绘规划 Demo",
                template="survey",
                waypoints=[
                    {"lat": 30.5600, "lng": 104.1000, "alt": 150},
                    {"lat": 30.5650, "lng": 104.1100, "alt": 150},
                ],
                params={"grid_spacing": 30},
                status="draft",
                created_at=NOW - timedelta(minutes=10),
            ),
        ]
        db.add_all(missions)

        # --- approvals ---
        approvals = [
            FlightApproval(
                id=uuid4(),
                tenant_id=org.id,
                title="城南物流航线日常飞行申请",
                category="routine",
                purpose="物流配送航线测试",
                pilot_name="王飞",
                pilot_license="UAS-2025-08871",
                aircraft_reg="UAS-CD-0031",
                aircraft_model="FAKE-VTOL-300",
                insurance_no="INS-2026-77201",
                area_polygon=[
                    {"lat": 30.55, "lng": 104.05},
                    {"lat": 30.59, "lng": 104.05},
                    {"lat": 30.59, "lng": 104.09},
                    {"lat": 30.55, "lng": 104.09},
                ],
                max_alt_m=120.0,
                min_alt_m=30.0,
                start_ts=NOW + timedelta(hours=2),
                end_ts=NOW + timedelta(hours=5),
                status="pending",
            ),
            FlightApproval(
                id=uuid4(),
                tenant_id=org.id,
                title="青龙湖公园航拍活动申请",
                category="routine",
                purpose="文旅宣传航拍",
                pilot_name="李云",
                pilot_license="UAS-2025-10233",
                aircraft_reg="UAS-CD-0102",
                aircraft_model="FAKE-QUAD-150",
                insurance_no="INS-2026-77312",
                area_polygon=[
                    {"lat": 30.65, "lng": 104.15},
                    {"lat": 30.68, "lng": 104.15},
                    {"lat": 30.68, "lng": 104.19},
                    {"lat": 30.65, "lng": 104.19},
                ],
                max_alt_m=90.0,
                min_alt_m=20.0,
                start_ts=NOW + timedelta(days=1),
                end_ts=NOW + timedelta(days=1, hours=3),
                status="pending",
            ),
            FlightApproval(
                id=uuid4(),
                tenant_id=org.id,
                title="环城生态带夜间巡检申请",
                category="special",
                purpose="生态带火情夜间巡查",
                pilot_name="张夜",
                pilot_license="UAS-2024-04560",
                aircraft_reg="UAS-CD-0210",
                aircraft_model="FAKE-VTOL-300",
                insurance_no="INS-2026-76550",
                area_polygon=[
                    {"lat": 30.60, "lng": 104.00},
                    {"lat": 30.63, "lng": 104.00},
                    {"lat": 30.63, "lng": 104.04},
                    {"lat": 30.60, "lng": 104.04},
                ],
                max_alt_m=150.0,
                min_alt_m=50.0,
                start_ts=NOW - timedelta(days=2),
                end_ts=NOW - timedelta(days=2, hours=-3),
                status="approved",
            ),
        ]
        db.add_all(approvals)
        await db.commit()
        print(f"seeded: {len(missions)} missions, {len(approvals)} approvals")


asyncio.run(main())
