import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { createActor } from "xstate";
import {
  type DirectorState,
  directorStateSchema,
  type MeshDescription,
  parsePoseFrame,
  type SceneDescription,
} from "./contracts";
import { loadScene, submitCommand } from "./director-api";
import { describeStep } from "./plan-presentation";
import { PoseTimeline } from "./pose-timeline";
import { sessionConnection } from "./session-connection";
import { publishSessionState, viewerId } from "./session-state";
import "./style.css";

interface CharacterRig {
  root: THREE.Group;
  bones: THREE.Bone[];
}

function requiredElement<ElementType extends HTMLElement>(
  selector: string,
): ElementType {
  const element = document.querySelector<ElementType>(selector);
  if (!element) throw new Error(`Missing interface element: ${selector}`);
  return element;
}

const canvas = requiredElement<HTMLCanvasElement>("#scene");
const connection = requiredElement("#connection");
const instructionInput = requiredElement<HTMLTextAreaElement>("#instruction");
const statusElement = requiredElement("#status");
const targetsToggle = requiredElement<HTMLInputElement>("#show-targets");
const followButton = requiredElement<HTMLButtonElement>("#follow");
const loadingElement = requiredElement("#loading");
const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  powerPreference: "high-performance",
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene();
scene.background = new THREE.Color("#edf2fb");
scene.fog = new THREE.Fog("#edf2fb", 35, 90);
const camera = new THREE.PerspectiveCamera(42, 1, 0.05, 150);
camera.up.set(0, 0, 1);
camera.position.set(-12, -1, 3.8);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.12;
controls.maxPolarAngle = Math.PI / 2 - 0.03;
controls.minDistance = 3;
controls.maxDistance = 55;
controls.target.set(-8, 4, 1);
scene.add(new THREE.HemisphereLight(0xffffff, 0x6a7d9b, 1.8));
const sunlight = new THREE.DirectionalLight(0xffffff, 1.8);
sunlight.position.set(-8, -12, 25);
sunlight.castShadow = true;
sunlight.shadow.mapSize.set(2048, 2048);
sunlight.shadow.camera.left = -35;
sunlight.shadow.camera.right = 35;
sunlight.shadow.camera.top = 35;
sunlight.shadow.camera.bottom = -35;
sunlight.shadow.normalBias = 0.025;
scene.add(sunlight);
const floorTextureCanvas = document.createElement("canvas");
floorTextureCanvas.width = 128;
floorTextureCanvas.height = 128;
const floorTextureContext = floorTextureCanvas.getContext("2d");
if (!floorTextureContext)
  throw new Error("The floor texture could not be created.");
floorTextureContext.fillStyle = "#d2def0";
floorTextureContext.fillRect(0, 0, 128, 128);
floorTextureContext.strokeStyle = "#c0cfe5";
floorTextureContext.lineWidth = 1;
floorTextureContext.strokeRect(0, 0, 128, 128);
const floorTexture = new THREE.CanvasTexture(floorTextureCanvas);
floorTexture.colorSpace = THREE.SRGBColorSpace;
floorTexture.wrapS = THREE.RepeatWrapping;
floorTexture.wrapT = THREE.RepeatWrapping;
floorTexture.repeat.set(180, 180);
floorTexture.anisotropy = renderer.capabilities.getMaxAnisotropy();
const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(180, 180),
  new THREE.MeshStandardMaterial({ map: floorTexture, roughness: 1 }),
);
floor.receiveShadow = true;
floor.position.z = -0.03;
scene.add(floor);

const routeGeometry = new THREE.BufferGeometry();
const routePositionBuffer = new THREE.Float32BufferAttribute(
  new Float32Array(130 * 3),
  3,
);
routeGeometry.setAttribute("position", routePositionBuffer);
const routeLine = new THREE.Line(
  routeGeometry,
  new THREE.LineBasicMaterial({
    color: 0x5571da,
    transparent: true,
    opacity: 0.55,
  }),
);
const waypointMarker = new THREE.Mesh(
  new THREE.RingGeometry(0.28, 0.4, 48),
  new THREE.MeshBasicMaterial({
    color: 0x3b55db,
    side: THREE.DoubleSide,
    depthWrite: false,
  }),
);
scene.add(routeLine, waypointMarker);
const proposedRoute = new THREE.Line(
  new THREE.BufferGeometry(),
  new THREE.LineDashedMaterial({
    color: 0x3b55db,
    transparent: true,
    opacity: 0.45,
    dashSize: 0.24,
    gapSize: 0.15,
  }),
);
const proposedWaypoints = new THREE.InstancedMesh(
  new THREE.RingGeometry(0.07, 0.12, 16),
  new THREE.MeshBasicMaterial({ color: 0x3b55db, side: THREE.DoubleSide }),
  128,
);
const bodyPins = new THREE.InstancedMesh(
  new THREE.SphereGeometry(0.045, 12, 8),
  new THREE.MeshBasicMaterial({
    color: 0xc54d9a,
    depthTest: false,
    transparent: true,
    opacity: 0.85,
  }),
  4,
);
bodyPins.visible = false;
bodyPins.renderOrder = 5;
scene.add(bodyPins);
const surfaceGoalMarker = new THREE.Mesh(
  new THREE.SphereGeometry(0.085, 16, 12),
  new THREE.MeshBasicMaterial({ color: 0xf0a32f, depthTest: false }),
);
const measuredHandMarker = new THREE.Mesh(
  new THREE.SphereGeometry(0.05, 12, 8),
  new THREE.MeshBasicMaterial({ color: 0x53bb94, depthTest: false }),
);
const surfaceErrorLine = new THREE.Line(
  new THREE.BufferGeometry(),
  new THREE.LineBasicMaterial({ color: 0xf0a32f, depthTest: false }),
);
surfaceGoalMarker.renderOrder =
  measuredHandMarker.renderOrder =
  surfaceErrorLine.renderOrder =
    6;
surfaceGoalMarker.visible =
  measuredHandMarker.visible =
  surfaceErrorLine.visible =
    false;
scene.add(surfaceGoalMarker, measuredHandMarker, surfaceErrorLine);
let hasSurfaceGoal = false;
let hasSurfaceMeasurement = false;
let planningViewRevision = -1;
let planningConnection = 0;
let hasBodyTarget = false;
const finalHeading = new THREE.ArrowHelper(
  new THREE.Vector3(1, 0, 0),
  new THREE.Vector3(),
  1.4,
  0x3b55db,
  0.3,
  0.2,
);
scene.add(proposedRoute, proposedWaypoints, finalHeading);
proposedRoute.visible = false;
proposedWaypoints.visible = false;
finalHeading.visible = false;
let proposedWaypointCount = 0;
let hasFinalHeading = false;
routeLine.visible = false;
waypointMarker.visible = false;

const previewContainer = requiredElement("#target-preview");
const previewRenderer = new THREE.WebGLRenderer({
  canvas: requiredElement<HTMLCanvasElement>("#target-preview-canvas"),
  antialias: true,
});
previewRenderer.setSize(188, 218, false);
previewRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
previewRenderer.outputColorSpace = THREE.SRGBColorSpace;
const previewScene = new THREE.Scene();
previewScene.background = new THREE.Color("#f4fafd");
previewScene.add(new THREE.HemisphereLight(0xffffff, 0x8097ad, 2.2));
const previewLight = new THREE.DirectionalLight(0xffffff, 2);
previewLight.position.set(2, -2, 4);
previewScene.add(previewLight);
const previewCamera = new THREE.PerspectiveCamera(36, 188 / 218, 0.05, 20);
previewCamera.up.set(0, 0, 1);
let previewRig: CharacterRig | null = null;
let previewNeedsUpdate = true;
let previewSignature = "";

function renderTargetPreview(frame: Float32Array, offset: number): void {
  if (!previewRig) return;
  applyPose(previewRig, frame, offset);
  previewRig.bones[0].position.x = 0;
  previewRig.bones[0].position.y = 0;
  const facing = new THREE.Vector3(0, 1, 0)
    .applyQuaternion(previewRig.bones[0].quaternion)
    .setZ(0)
    .normalize();
  const left = new THREE.Vector3(-facing.y, facing.x, 0);
  previewCamera.position
    .copy(facing.multiplyScalar(3.8))
    .addScaledVector(left, 2)
    .setZ(1.8);
  previewCamera.lookAt(0, 0, 0.95);
  previewRenderer.render(previewScene, previewCamera);
  previewNeedsUpdate = false;
}

let character: CharacterRig | null = null;
let targetRigs: CharacterRig[] = [];
let jointCount = 0;
let currentPose: Float32Array | null = null;
const poseTimeline = new PoseTimeline(100);
let lastFrameReceivedAt = 0;
let lastSequence = -1;
let followCharacter = true;
let previousRoot: THREE.Vector3 | null = null;
let activeTargetCount = 0;
const interpolatedPosition = new THREE.Vector3();
const nextPosition = new THREE.Vector3();
const interpolatedRotation = new THREE.Quaternion();
const nextRotation = new THREE.Quaternion();
const unitScale = new THREE.Vector3(1, 1, 1);

// SOMA uses ten influences per vertex. Preserve all ten rather than reducing
// the mesh to Three's default four and changing how the character deforms.
function supportAllInfluences(material: THREE.Material): void {
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader.replace(
      "#include <skinning_pars_vertex>",
      `#include <skinning_pars_vertex>
attribute vec4 skinIndexExtra; attribute vec4 skinWeightExtra;
attribute vec4 skinIndexTail; attribute vec4 skinWeightTail;`,
    );
    let weightedMatrices =
      "mat4 fullSkinMatrix = boneMatX * skinWeight.x + boneMatY * skinWeight.y + boneMatZ * skinWeight.z + boneMatW * skinWeight.w;\n";
    for (const suffix of ["Extra", "Tail"]) {
      for (const component of ["x", "y", "z", "w"]) {
        weightedMatrices += `fullSkinMatrix += getBoneMatrix(skinIndex${suffix}.${component}) * skinWeight${suffix}.${component};\n`;
      }
    }
    shader.vertexShader = shader.vertexShader.replace(
      "#include <skinbase_vertex>",
      `#include <skinbase_vertex>\n${weightedMatrices}`,
    );
    shader.vertexShader = shader.vertexShader.replace(
      "#include <skinnormal_vertex>",
      `mat4 skinMatrix = bindMatrixInverse * fullSkinMatrix * bindMatrix;
objectNormal = (skinMatrix * vec4(objectNormal, 0.0)).xyz;
#ifdef USE_TANGENT
objectTangent = (skinMatrix * vec4(objectTangent, 0.0)).xyz;
#endif`,
    );
    shader.vertexShader = shader.vertexShader.replace(
      "#include <skinning_vertex>",
      "transformed = (bindMatrixInverse * fullSkinMatrix * bindMatrix * vec4(transformed, 1.0)).xyz;",
    );
  };
  material.customProgramCacheKey = () => "motionbricks-full-skinning-v1";
}

function createGeometry(description: MeshDescription): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(description.positions, 3),
  );
  geometry.setIndex(description.indices);
  const vertexCount = description.positions.length / 3;
  for (const [groupIndex, suffix] of ["", "Extra", "Tail"].entries()) {
    const indices = new Uint16Array(vertexCount * 4);
    const weights = new Float32Array(vertexCount * 4);
    for (let vertexIndex = 0; vertexIndex < vertexCount; vertexIndex++) {
      for (let component = 0; component < 4; component++) {
        const influenceIndex = groupIndex * 4 + component;
        if (influenceIndex >= description.influences) continue;
        const sourceIndex =
          vertexIndex * description.influences + influenceIndex;
        indices[vertexIndex * 4 + component] =
          description.jointIndices[sourceIndex];
        weights[vertexIndex * 4 + component] =
          description.jointWeights[sourceIndex];
      }
    }
    geometry.setAttribute(
      `skinIndex${suffix}`,
      new THREE.Uint16BufferAttribute(indices, 4),
    );
    geometry.setAttribute(
      `skinWeight${suffix}`,
      new THREE.Float32BufferAttribute(weights, 4),
    );
  }
  geometry.computeVertexNormals();
  return geometry;
}

function createRig(
  description: SceneDescription,
  geometries: THREE.BufferGeometry[],
  ghostIndex: number | null,
  destinationScene: THREE.Scene = scene,
): CharacterRig {
  const root = new THREE.Group();
  const bones = description.jointNames.map((name) => {
    const bone = new THREE.Bone();
    bone.name = name;
    return bone;
  });
  for (const [jointIndex, parentIndex] of description.parents.entries()) {
    if (parentIndex < 0) root.add(bones[jointIndex]);
    else bones[parentIndex].add(bones[jointIndex]);
  }
  const inverseBind = description.inverseBind.map(
    ([x, y, z, qx, qy, qz, qw]) => {
      return new THREE.Matrix4().compose(
        new THREE.Vector3(x, y, z),
        new THREE.Quaternion(qx, qy, qz, qw),
        unitScale,
      );
    },
  );
  const skeleton = new THREE.Skeleton(bones, inverseBind);
  for (const geometry of geometries) {
    const material = new THREE.MeshStandardMaterial({
      color: ghostIndex === null ? 0xf7f8fc : 0x13acc4,
      roughness: 0.72,
      transparent: ghostIndex !== null,
      opacity: ghostIndex === null ? 1 : 0.1 + ghostIndex * 0.025,
      depthWrite: ghostIndex === null,
    });
    supportAllInfluences(material);
    const mesh = new THREE.SkinnedMesh(geometry, material);
    mesh.bind(skeleton, new THREE.Matrix4());
    mesh.frustumCulled = false;
    mesh.castShadow = ghostIndex === null;
    if (ghostIndex === null) {
      const depthMaterial = new THREE.MeshDepthMaterial({
        depthPacking: THREE.RGBADepthPacking,
      });
      supportAllInfluences(depthMaterial);
      mesh.customDepthMaterial = depthMaterial;
    }
    root.add(mesh);
  }
  destinationScene.add(root);
  return { root, bones };
}

function applyPose(rig: CharacterRig, pose: Float32Array, offset = 0): void {
  for (let jointIndex = 0; jointIndex < jointCount; jointIndex++) {
    const start = offset + jointIndex * 7;
    rig.bones[jointIndex].position.fromArray(pose, start);
    rig.bones[jointIndex].quaternion.fromArray(pose, start + 3);
  }
}

function receivePose(data: ArrayBuffer): void {
  const parsed = parsePoseFrame(data, jointCount);
  if (!parsed || parsed.sequence <= lastSequence) return;
  const { frame, sequence, simulationSeconds, targetCount, waypointCount } =
    parsed;
  lastSequence = sequence;
  currentPose = frame.slice(4, 4 + jointCount * 7);
  lastFrameReceivedAt = performance.now();
  poseTimeline.enqueuePose(simulationSeconds, currentPose, lastFrameReceivedAt);
  if (connection.classList.contains("connected"))
    connection.textContent = "Live gym";
  activeTargetCount = targetCount;
  for (const [targetIndex, rig] of targetRigs.entries()) {
    rig.root.visible = targetsToggle.checked && targetIndex < targetCount;
    if (targetIndex < targetCount)
      applyPose(rig, frame, 4 + jointCount * 7 * (targetIndex + 1));
  }
  if (hasBodyTarget && previewNeedsUpdate && targetCount === 1)
    renderTargetPreview(frame, 4 + jointCount * 7);
  const routeOffset = 4 + jointCount * 7 * (1 + targetCount);
  const routePositions = [currentPose[0], currentPose[1], 0.025];
  for (let waypointIndex = 0; waypointIndex < waypointCount; waypointIndex++) {
    routePositions.push(
      frame[routeOffset + waypointIndex * 3],
      frame[routeOffset + waypointIndex * 3 + 1],
      0.025,
    );
  }
  routePositionBuffer.array.set(
    routePositions.slice(0, routePositionBuffer.array.length),
  );
  routePositionBuffer.needsUpdate = true;
  routeGeometry.setDrawRange(0, Math.min(waypointCount + 1, 130));
  routeGeometry.computeBoundingSphere();
  routeLine.visible = targetsToggle.checked && waypointCount > 0;
  waypointMarker.visible = routeLine.visible;
  if (waypointCount > 0)
    waypointMarker.position.set(
      frame[routeOffset],
      frame[routeOffset + 1],
      0.03,
    );
}

let renderedRouteSignature = "";
function updateState(state: DirectorState): void {
  if (state.model) {
    const modelName =
      state.model === "gemini-4-argon" ? "Gemini 4 Argon" : state.model;
    const modelElement = requiredElement("#model-name");
    if (modelElement.textContent !== modelName) {
      modelElement.textContent = modelName;
      document.title = `${modelName} × MotionBricks | Spatial character director`;
    }
  }
  publishSessionState(state);
  const measuredContact = state.bodyTarget?.contact;
  const plannedContact = state.steps
    .slice(state.stepIndex)
    .find((step) => step.body_pose?.contact)?.body_pose?.contact;
  const surfacePosition = measuredContact?.position ?? plannedContact?.position;
  const surfaceObject =
    measuredContact?.objectName ?? plannedContact?.object_name;
  const surfaceEffector = measuredContact?.effector ?? plannedContact?.effector;
  hasSurfaceGoal = surfacePosition !== undefined;
  hasSurfaceMeasurement = measuredContact?.actual !== undefined;
  surfaceGoalMarker.visible = targetsToggle.checked && hasSurfaceGoal;
  measuredHandMarker.visible = surfaceErrorLine.visible =
    targetsToggle.checked && hasSurfaceMeasurement;
  if (surfacePosition) surfaceGoalMarker.position.fromArray(surfacePosition);
  if (surfacePosition && measuredContact?.actual) {
    measuredHandMarker.position.fromArray(measuredContact.actual);
    surfaceErrorLine.geometry.setFromPoints([
      new THREE.Vector3(...surfacePosition),
      new THREE.Vector3(...measuredContact.actual),
    ]);
  }
  requiredElement("#surface-reach").hidden = !hasSurfaceGoal;
  requiredElement("#surface-reach-goal").textContent = surfacePosition
    ? `${surfaceEffector?.replace("_", " ")} → ${surfaceObject} · world (${surfacePosition.map((value) => value.toFixed(2)).join(", ")}) m`
    : "";
  requiredElement("#surface-reach-error").textContent =
    measuredContact?.errorMeters !== undefined
      ? `Hand distance: ${(measuredContact.errorMeters * 100).toFixed(1)} cm${measuredContact.beforeHoldError !== undefined ? ` · before hold: ${(measuredContact.beforeHoldError * 100).toFixed(1)} cm` : ""}`
      : "Amber marks Gemini’s generated goal. Approaching a reachable standing position…";
  const planningView = state.planningView;
  requiredElement("#planning-view").hidden = !planningView?.available;
  if (
    planningView?.available &&
    planningView.revision !== planningViewRevision
  ) {
    planningViewRevision = planningView.revision;
    const planningImageUrl = new URL(
      `planning-view.jpg?revision=${planningView.revision}&connection=${planningConnection}`,
      document.baseURI,
    ).href;
    requiredElement<HTMLImageElement>("#planning-view-image").src =
      planningImageUrl;
    requiredElement<HTMLAnchorElement>("#planning-view-link").href =
      planningImageUrl;
  }
  hasBodyTarget = state.bodyTarget !== null;
  previewContainer.hidden = !hasBodyTarget || !targetsToggle.checked;
  const targetSignature = JSON.stringify([
    state.bodyTarget?.desired ?? null,
    state.bodyTarget?.pelvisHeight,
    state.stepIndex,
  ]);
  if (targetSignature !== previewSignature) {
    previewSignature = targetSignature;
    previewNeedsUpdate = true;
  }
  bodyPins.visible = targetsToggle.checked && hasBodyTarget;
  if (state.bodyTarget) {
    const positions = Object.values(state.bodyTarget.desired);
    bodyPins.count = positions.length;
    for (const [index, position] of positions.entries())
      bodyPins.setMatrixAt(
        index,
        new THREE.Matrix4().makeTranslation(...position),
      );
    bodyPins.instanceMatrix.needsUpdate = true;
    bodyPins.computeBoundingSphere();
  }
  const currentStep = state.steps[state.stepIndex];
  const completed = state.status.startsWith("Done.");
  const rejected =
    state.recentOutcomes[0]?.outcome === state.status && !completed;
  const phase = state.planning
    ? "planning"
    : state.active
      ? "running"
      : completed
        ? "complete"
        : rejected
          ? "rejected"
          : "ready";
  requiredElement("#plan-board").dataset.phase = phase;
  requiredElement("#plan-board").setAttribute(
    "aria-busy",
    String(state.planning),
  );
  requiredElement("#plan-phase").textContent = state.planning
    ? state.steps.length
      ? "Repairing target…"
      : "Generating plan…"
    : state.active
      ? `Step ${state.stepIndex + 1} of ${state.steps.length}`
      : completed
        ? "Complete"
        : rejected
          ? "Plan rejected"
          : "Ready";
  const instruction =
    state.activeInstruction?.instruction ??
    (state.steps.length ? state.recentOutcomes[0]?.instruction : "") ??
    "";
  requiredElement("#plan-instruction").textContent = instruction;
  requiredElement("#plan-instruction").title = instruction;
  statusElement.textContent =
    state.active && currentStep && !state.planning
      ? `Step ${state.stepIndex + 1} of ${state.steps.length}: ${describeStep(currentStep)}`
      : state.status;
  const spatialTargets = state.steps.flatMap((step) => step.waypoints);
  const signature = JSON.stringify([spatialTargets, state.planningOrigin]);
  if (signature !== renderedRouteSignature) {
    proposedWaypointCount = spatialTargets.length;
    const vertices = spatialTargets.flatMap((waypoint) => [
      waypoint.position[0],
      waypoint.position[1],
      0.035,
    ]);
    if (state.planningOrigin) vertices.unshift(...state.planningOrigin, 0.035);
    proposedRoute.geometry.dispose();
    proposedRoute.geometry = new THREE.BufferGeometry().setAttribute(
      "position",
      new THREE.Float32BufferAttribute(vertices, 3),
    );
    proposedRoute.computeLineDistances();
    proposedWaypoints.count = spatialTargets.length;
    for (const [index, waypoint] of spatialTargets.entries())
      proposedWaypoints.setMatrixAt(
        index,
        new THREE.Matrix4().makeTranslation(...waypoint.position, 0.04),
      );
    proposedWaypoints.instanceMatrix.needsUpdate = true;
    proposedWaypoints.computeBoundingSphere();
    const stoppingTarget = spatialTargets.at(-1);
    hasFinalHeading =
      stoppingTarget?.heading_degrees !== null &&
      stoppingTarget?.heading_degrees !== undefined;
    if (stoppingTarget && hasFinalHeading) {
      const radians = THREE.MathUtils.degToRad(
        stoppingTarget.heading_degrees ?? 0,
      );
      finalHeading.position.set(...stoppingTarget.position, 0.04);
      finalHeading.setDirection(
        new THREE.Vector3(Math.cos(radians), Math.sin(radians), 0),
      );
    }
    proposedRoute.visible = targetsToggle.checked && proposedWaypointCount > 0;
    proposedWaypoints.visible = proposedRoute.visible;
    finalHeading.visible = targetsToggle.checked && hasFinalHeading;
    renderedRouteSignature = signature;
  }
}

async function sendCommand(
  command: Parameters<typeof submitCommand>[0],
): Promise<void> {
  try {
    await submitCommand(command);
  } catch (error) {
    statusElement.textContent =
      error instanceof Error ? error.message : "Connection failed. Try again.";
  }
}

requiredElement("#instruction-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!instructionInput.value.trim()) return;
  statusElement.textContent = "Sending your instruction…";
  void sendCommand({
    path: "instruction",
    payload: {
      instruction: instructionInput.value,
      viewerId,
    },
  });
});
requiredElement("#stop").addEventListener("click", () => {
  statusElement.textContent = "Stopping…";
  void sendCommand({ path: "stop" });
});
requiredElement("#clear-queue").addEventListener("click", () => {
  void sendCommand({ path: "clear-queue" });
});
requiredElement("#reset").addEventListener("click", () => {
  previousRoot = null;
  void sendCommand({ path: "reset" });
});
for (const button of document.querySelectorAll<HTMLButtonElement>(
  "[data-instruction]",
)) {
  button.addEventListener("click", () => {
    instructionInput.value = button.dataset.instruction ?? "";
    instructionInput.focus();
  });
}
targetsToggle.addEventListener("change", () => {
  surfaceGoalMarker.visible = targetsToggle.checked && hasSurfaceGoal;
  measuredHandMarker.visible = surfaceErrorLine.visible =
    targetsToggle.checked && hasSurfaceMeasurement;
  previewContainer.hidden = !hasBodyTarget || !targetsToggle.checked;
  bodyPins.visible = targetsToggle.checked && hasBodyTarget;
  proposedRoute.visible = targetsToggle.checked && proposedWaypointCount > 0;
  proposedWaypoints.visible = proposedRoute.visible;
  finalHeading.visible = targetsToggle.checked && hasFinalHeading;
  for (const [index, rig] of targetRigs.entries())
    rig.root.visible = targetsToggle.checked && index < activeTargetCount;
  if (!targetsToggle.checked) {
    routeLine.visible = false;
    waypointMarker.visible = false;
  }
});
followButton.addEventListener("click", () => {
  followCharacter = !followCharacter;
  followButton.setAttribute("aria-pressed", String(followCharacter));
  previousRoot = null;
  if (followCharacter && currentPose) {
    controls.target.set(currentPose[0], currentPose[1], 1);
    camera.position.set(currentPose[0] - 6, currentPose[1] - 7, 5);
  }
});
requiredElement("#pose-view").addEventListener("click", () => {
  if (!currentPose) return;
  followCharacter = true;
  followButton.setAttribute("aria-pressed", "true");
  previousRoot = null;
  controls.target.set(currentPose[0], currentPose[1], 1);
  camera.position.set(currentPose[0] + 4, currentPose[1] - 4.5, 2.8);
});
requiredElement("#overview").addEventListener("click", () => {
  followCharacter = false;
  followButton.setAttribute("aria-pressed", "false");
  controls.target.set(0, 4, 0);
  camera.position.set(-22, -18, 24);
});

function connect(): void {
  const socketUrl = new URL("ws", document.baseURI);
  socketUrl.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const actor = createActor(sessionConnection, {
    input: {
      url: socketUrl,
      onOpen: () => {
        planningViewRevision = -1;
        planningConnection++;
        lastSequence = -1;
        lastFrameReceivedAt = performance.now();
        poseTimeline.reset();
        loadingElement.hidden = true;
      },
      onMessage: (data) => {
        if (data instanceof ArrayBuffer) {
          receivePose(data);
          return;
        }
        let payload: unknown;
        try {
          payload = JSON.parse(String(data));
        } catch {
          statusElement.textContent =
            "The session sent unreadable data. Refresh to reconnect.";
          return;
        }
        const state = directorStateSchema.safeParse(payload);
        if (!state.success) {
          statusElement.textContent =
            "The session data is incompatible. Refresh to reconnect.";
          return;
        }
        updateState(state.data);
      },
    },
  });
  actor.subscribe((snapshot) => {
    const live = snapshot.matches({ connecting: "live" });
    connection.dataset.live = String(live);
    connection.textContent = live ? "Live gym" : "Reconnecting…";
    connection.classList.toggle("connected", live);
    for (const selector of ["#direct", "#stop", "#reset", "#clear-queue"])
      requiredElement<HTMLButtonElement>(selector).disabled = !live;
  });
  actor.start();
  window.addEventListener("pagehide", () => actor.stop(), { once: true });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });
}

let viewportWidth = 0;
let viewportHeight = 0;
function animate(): void {
  requestAnimationFrame(animate);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (
    width > 0 &&
    height > 0 &&
    (width !== viewportWidth || height !== viewportHeight)
  ) {
    viewportWidth = width;
    viewportHeight = height;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  const playback = poseTimeline.samplePose(performance.now());
  if (character && playback) {
    const { before, after, blend } = playback;
    for (let jointIndex = 0; jointIndex < jointCount; jointIndex++) {
      const offset = jointIndex * 7;
      interpolatedPosition
        .fromArray(before, offset)
        .lerp(nextPosition.fromArray(after, offset), blend);
      interpolatedRotation.fromArray(before, offset + 3);
      nextRotation.fromArray(after, offset + 3);
      interpolatedRotation.slerp(nextRotation, blend);
      character.bones[jointIndex].position.copy(interpolatedPosition);
      character.bones[jointIndex].quaternion.copy(interpolatedRotation);
    }
    const rootPosition = character.bones[0].position.clone().setZ(0);
    if (followCharacter && previousRoot) {
      const displacement = rootPosition.clone().sub(previousRoot);
      camera.position.add(displacement);
      controls.target.add(displacement);
    } else if (followCharacter) {
      const viewOffset = camera.position.clone().sub(controls.target);
      controls.target.set(rootPosition.x, rootPosition.y, 1);
      camera.position.copy(controls.target).add(viewOffset);
    }
    previousRoot = rootPosition;
    if (connection.dataset.live === "true")
      connection.textContent =
        performance.now() - lastFrameReceivedAt > 4000
          ? "Waiting for motion…"
          : "Live gym";
  }
  controls.update();
  renderer.render(scene, camera);
}

async function initialize(): Promise<void> {
  const description = await loadScene();
  jointCount = description.jointNames.length;
  const geometries = description.meshes.map(createGeometry);
  character = createRig(description, geometries, null);
  previewRig = createRig(description, geometries, null, previewScene);
  previewRig.root.traverse((node) => {
    if (
      node instanceof THREE.SkinnedMesh &&
      node.material instanceof THREE.MeshStandardMaterial
    ) {
      node.material.color.set(0x13acc4);
      node.castShadow = false;
    }
  });
  targetRigs = Array.from({ length: 4 }, (_, index) =>
    createRig(description, geometries, index),
  );
  for (const rig of targetRigs) rig.root.visible = false;
  for (const object of description.objects) {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(...object.size),
      new THREE.MeshStandardMaterial({
        color: new THREE.Color(...object.color),
        roughness: 0.65,
      }),
    );
    mesh.position.fromArray(object.transform);
    mesh.quaternion.fromArray(object.transform, 3);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    scene.add(mesh);
  }
  connect();
  animate();
}

void initialize().catch((error: unknown) => {
  loadingElement.textContent =
    error instanceof Error ? error.message : "The viewer could not load.";
});
