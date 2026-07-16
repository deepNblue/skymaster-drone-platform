"""Register all ORM models with the declarative Base."""
from app.models.audit_log import AuditLog
from app.models.active_session import ActiveSession
from app.models.backup_code import BackupCode
from app.models.flight_approval import (
    FlightApproval, FlightApprovalAuthority, FlightApprovalSignature,
)
from app.models.vision_copilot import VisionDetection, CopilotSessionV2, CopilotTurnV2
from app.models.community import CommunityPost, CommunityComment, CommunityReport
from app.models.aaas import AaasClient, AaasDelivery
from app.models.copilot_workflow import CopilotWorkflow
from app.models.copilot_workflow_run import CopilotWorkflowRun
from app.models.copilot_workflow_schedule import CopilotWorkflowSchedule
from app.models.community_playbook import CommunityPlaybook
from app.models.approval_template import ApprovalTemplate
from app.models.airspace_calendar import AirspaceCalendarEntry
from app.models.marketplace_monetization import (
    ModelListingPrice, ModelPurchaseOrder,
)
from app.models.video_stream import VideoStream, VideoStreamProbe
from app.models.model_marketplace import (
    ModelDeployment, ModelListing, ModelUsageEvent, ModelVersion,
)
from app.models.drone import Drone
from app.models.flight_log import FlightLog
from app.models.login_event import LoginEvent
from app.models.media_asset import MediaAsset
from app.models.mission import Mission
from app.models.organization import Organization
from app.models.password_reset_token import PasswordResetToken
from app.models.revoked_token import RevokedToken
from app.models.scene import Scene, SceneAsset
from app.models.scene_marketplace import (
    SceneListing, SceneListingClone, SceneListingReview,
)
from app.models.scene_moderation import (
    SceneListingAppeal, SceneListingReport,
)
from app.models.scene_job import SceneJob
from app.models.user import User

__all__ = [
    "ActiveSession",
    "AuditLog",
    "BackupCode",
    "FlightApproval",
    "FlightApprovalAuthority",
    "VisionDetection",
    "CopilotSessionV2",
    "CopilotTurnV2",
    "CopilotWorkflow",
    "CopilotWorkflowRun",
    "Drone",
    "FlightLog",
    "LoginEvent",
    "MediaAsset",
    "Mission",
    "Organization",
    "PasswordResetToken",
    "RevokedToken",
    "Scene",
    "SceneAsset",
    "SceneListing",
    "SceneListingClone",
    "SceneListingReview",
    "SceneListingReport",
    "SceneListingAppeal",
    "SceneJob",
    "User",
]
