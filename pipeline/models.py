"""Internal scene data uses Blender right-handed Z-up meters and XYZ Euler degrees.

Assets have bottom-centered origins, local +Y forward, and reference boxes in
normalized image coordinates (left, top, right, bottom). Pose targets are world
coordinates. Camera landmarks are normalized image coordinates, top-left origin.
"""
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


Vec3 = tuple[float, float, float]
Positive = Annotated[float, Field(gt=0)]


class CodexConfig(Record):
    executable: str
    model: Literal["gpt-6-astra"]
    reasoning: Literal["low", "medium", "high", "xhigh", "max", "ultra"]
    concurrency: Annotated[int, Field(ge=1, le=2)]
    timeout_seconds: Positive


class GlmConfig(Record):
    endpoint: Annotated[str, Field(pattern=r"^https?://")]
    model: str
    concurrency: Annotated[int, Field(ge=1)]
    timeout_seconds: Positive
    max_tokens: Positive
    enable_thinking: bool = True
    structured_decoding: bool = True


class Spending(Record):
    authorization: str | None
    unlimited_authorized: bool
    max_credits: Annotated[float, Field(ge=0)] | None
    max_submissions: Annotated[int, Field(ge=0)] | None
    image_credits_upper_bound: Positive
    preview_credits_upper_bound: Positive
    refine_credits_upper_bound: Positive
    rig_credits_upper_bound: Positive
    remesh_credits_upper_bound: Positive

    @model_validator(mode="after")
    def authorized_limits(self):
        if not self.authorization or not self.authorization.strip():
            raise ValueError('Meshy requires explicit spending authorization')
        if (self.max_credits is None or self.max_submissions is None) and not self.unlimited_authorized:
            raise ValueError('Null spending limits require explicit unlimited authorization')
        return self


class MeshyConfig(Record):
    endpoint: Literal["https://api.staging.meshy.ai", "https://api.meshy.ai"]
    key_file: Path
    model: Literal["meshy-7"]
    concurrency: Annotated[int, Field(ge=1)]
    poll_seconds: Positive
    request_timeout_seconds: Positive
    remesh_route: Literal['/openapi/v1/remesh', '/openapi/v2/remesh']
    rig_target_polycount: Annotated[int, Field(ge=100, le=300000)]
    spending: Spending


class BlenderConfig(Record):
    executable: str
    resolution_height: Annotated[int, Field(ge=64, le=4096)]
    samples: Annotated[int, Field(ge=1)]
    pose_tolerance_meters: Positive
    reprojection_tolerance: Annotated[float, Field(gt=0, lt=1)]


class Config(Record):
    codex: CodexConfig
    inference_backend: Literal["codex", "glm"]
    glm: GlmConfig | None = None
    meshy: MeshyConfig
    blender: BlenderConfig
    deadline_seconds: Positive
    correction_count: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def backend(self):
        if self.inference_backend == "glm" and self.glm is None:
            raise ValueError('GLM inference backend requires a glm configuration block')
        return self

    @classmethod
    def read(cls, path):
        if path is None:
            raise ValueError("An explicit pipeline YAML config_path is required")
        try:
            data = yaml.safe_load(Path(path).read_text())
        except yaml.YAMLError:
            raise ValueError('Invalid pipeline YAML syntax') from None
        return cls.model_validate(data)


class Transform(Record):
    position: Vec3
    rotation_degrees: Vec3
    scale: Annotated[tuple[Positive, Positive, Positive],
                     Field(description="A dimensionless relative multiplier applied after height normalization; "
                                       "three strictly positive components, [1, 1, 1] means no scaling, and flat "
                                       "objects may use a small thin multiplier such as 0.1 but never 0")]


class Pose(Record):
    bone: str
    target: Vec3
    pole: Vec3
    chain_length: Annotated[int, Field(ge=1, le=4)]
    pole_angle_degrees: float


class Asset(Record):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
    role: Literal["character", "prop", "environment"]
    description: Annotated[str, Field(min_length=1, max_length=800)]
    visible_evidence: list[str]
    uncertain_completion: list[str]
    reference_crop: tuple[float, float, float, float] | None
    height_meters: Annotated[Positive, Field(description="The asset's standing height in meters that the mesh "
                                                          "is normalized to BEFORE the transform; strictly positive")]
    articulated: bool
    transform: Transform
    pose: list[Pose]

    @model_validator(mode="after")
    def consistent(self):
        if self.reference_crop is not None:
            x0, y0, x1, y1 = self.reference_crop
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError("Invalid reference crop")
        if self.pose and not self.articulated:
            raise ValueError("Pose requires an articulated asset")
        return self


class Primitive(Record):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
    shape: Literal["box", "sphere", "cylinder", "cone"]
    description: str
    transform: Transform
    color: tuple[float, float, float, float]
    metallic: Annotated[float, Field(ge=0, le=1)]
    roughness: Annotated[float, Field(ge=0, le=1)]
    emission: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def rgba(self):
        if not all(0 <= x <= 1 for x in self.color):
            raise ValueError("Color components must be in [0, 1]")
        return self


class Light(Record):
    kind: Literal["AREA", "SUN", "POINT"]
    position: Vec3
    target: Vec3
    color: tuple[float, float, float]
    energy: Positive
    size: Positive


class Camera(Record):
    position: Vec3
    target: Vec3
    up: Vec3
    projection: Literal["perspective", "orthographic"]
    fov_degrees: Annotated[float, Field(gt=0, lt=180)] | None
    orthographic_height: Positive | None
    aspect_ratio: Positive

    @model_validator(mode="after")
    def projection_fields(self):
        if self.projection == "perspective":
            if self.fov_degrees is None or self.orthographic_height is not None:
                raise ValueError("Perspective requires vertical FOV only")
        elif self.fov_degrees is not None or self.orthographic_height is None:
            raise ValueError("Orthographic requires vertical height only")
        direction = [b-a for a, b in zip(self.position, self.target)]
        cross = [direction[1]*self.up[2]-direction[2]*self.up[1],
                 direction[2]*self.up[0]-direction[0]*self.up[2],
                 direction[0]*self.up[1]-direction[1]*self.up[0]]
        if sum(x*x for x in cross) < 1e-12:
            raise ValueError("Camera direction and up must span a plane")
        return self

    def gltf(self):
        result = self.model_dump(mode="json")
        for field in ("position", "target", "up"):
            x, y, z = result[field]
            result[field] = [x, z, -y]
        return result


class Landmark(Record):
    asset_id: str
    point: Literal["bottom", "center", "top"]
    image_xy: tuple[float, float]


class Scene(Record):
    title: str
    summary: str
    assumptions: list[str]
    assets: Annotated[list[Asset], Field(min_length=1)]
    primitives: list[Primitive]
    lights: Annotated[list[Light], Field(min_length=1)]
    world_color: tuple[float, float, float]
    camera: Camera
    landmarks: list[Landmark]

    @model_validator(mode="after")
    def identities(self):
        ids = [a.id for a in self.assets] + [p.id for p in self.primitives]
        if len(ids) != len(set(ids)):
            raise ValueError("Scene identifiers must be unique")
        for landmark in self.landmarks:
            if landmark.asset_id not in ids or not all(0 <= x <= 1 for x in landmark.image_xy):
                raise ValueError("Invalid camera landmark")
        return self


class Inspection(Record):
    acceptable: bool
    observations: list[str]
    correction_reason: str | None
    corrected_scene: Scene | None
    regenerate_assets: list[str]

    @model_validator(mode="after")
    def reason(self):
        if self.corrected_scene is not None and not self.correction_reason:
            raise ValueError("Corrections need an explanation")
        ids = set() if self.corrected_scene is None else {asset.id for asset in self.corrected_scene.assets}
        if len(self.regenerate_assets) != len(set(self.regenerate_assets)) or not set(self.regenerate_assets) <= ids:
            raise ValueError('Regeneration must name unique assets in the corrected scene')
        return self
