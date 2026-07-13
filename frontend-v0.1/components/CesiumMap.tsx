'use client';

import React from 'react';
import dynamic from 'next/dynamic';

export interface Waypoint {
  seq?: number;
  lat: number;
  lng: number;
  alt?: number;
  [k: string]: any;
}

export interface Trail {
  droneId: string;
  points: Array<{ lat: number; lng: number; alt?: number }>;
  color?: string;   // Cesium color name, defaults per-drone
}

export interface GeoFenceZone {
  id: string;
  name: string;
  kind: 'no_fly' | 'restricted' | 'height';
  polygon: number[][];  // [[lng, lat], ...]
  max_alt_m?: number | null;
}

export interface CesiumMapProps {
  droneId?: string;
  droneIds?: string[];
  waypoints?: Waypoint[];
  trails?: Trail[];
  zones?: GeoFenceZone[];
  height?: number | string;
  onReady?: (viewer: any) => void;
  onDroneClick?: (droneId: string, telemetry: any) => void;
  /** Called with (lat, lng) when user left-clicks anywhere on the globe. */
  onMapClick?: (lat: number, lng: number) => void;
  /** Follow the primary drone with the camera. */
  followPrimary?: boolean;
}

// ---------------------------------------------------------------------------
// Cesium requires `window` at import-time. We isolate the actual viewer in a
// dynamically-imported inner module so Next.js does not try to render it on
// the server. The outer wrapper is a "use client" component that only exposes
// props and a fallback UI.
// ---------------------------------------------------------------------------

const CesiumMapDynamic = dynamic(
  async () => {
    // ---- Runtime-only imports (browser) -----------------------------------
    const React = await import('react');
    const { useEffect, useRef, useState } = React;
    const resium = await import('resium');
    const CesiumNS: any = await import('cesium');
    const { subscribeTelemetry } = await import('../lib/ws');

    // Cesium ships its own worker/asset files. When bundled by Next.js we
    // need to tell Cesium where to find them. `/cesium/` should be served
    // as a static asset (copied into public/cesium/ at build time).
    if (typeof window !== 'undefined') {
      (window as any).CESIUM_BASE_URL = '/cesium/';
      // Expose Cesium globally so parent components (e.g. the copilot-v2
      // dashboard) can build Cartesian3.fromDegrees(...) for flyTo without
      // re-importing the module themselves. Safe because dynamic() runs
      // client-only.
      (window as any).Cesium = CesiumNS.default || CesiumNS;
    }

    const {
      Viewer,
      Entity,
      PolylineGraphics,
      PointGraphics,
      LabelGraphics,
      BoxGraphics,
      CylinderGraphics,
      PolygonGraphics,
    } = resium as any;
    const Cesium = (CesiumNS.default || CesiumNS) as any;

    // -----------------------------------------------------------------------
    // Inner component actually consumed by next/dynamic
    // -----------------------------------------------------------------------
    const CesiumMapInner: React.FC<CesiumMapProps> = ({
      droneId,
      droneIds,
      waypoints,
      trails,
      zones,
      height = 600,
      onReady,
      onDroneClick,
      onMapClick,
      followPrimary,
    }) => {
      const viewerRef = useRef<any>(null);
      const readyDoneRef = useRef(false);
      const flownRef = useRef<Set<string>>(new Set());
      // Track a fleet: id → {lat, lng, alt, ts}. Single droneId is folded in.
      const [fleet, setFleet] = useState<
        Record<string, { lat: number; lng: number; alt: number; ts: number }>
      >({});
      const primaryId = droneId || (droneIds && droneIds[0]) || '';
      const drone = primaryId ? fleet[primaryId] : undefined;

      // --- Telemetry subscription (multi-drone) ----------------------------
      useEffect(() => {
        const ids = new Set<string>(droneIds || []);
        if (droneId) ids.add(droneId);
        if (ids.size === 0) return;

        const subs: { close: () => void }[] = [];
        for (const id of ids) {
          try {
            const sub = subscribeTelemetry(id, (msg: any) => {
              const lat = msg?.lat ?? msg?.latitude;
              const lng = msg?.lng ?? msg?.longitude;
              const alt = msg?.alt ?? msg?.altitude ?? 50;
              if (typeof lat === 'number' && typeof lng === 'number') {
                setFleet((prev) => ({
                  ...prev,
                  [id]: { lat, lng, alt, ts: Date.now() },
                }));
                if (onDroneClick && msg?.__click) onDroneClick(id, msg);
              }
            });
            subs.push(sub);
          } catch (e) {
            // eslint-disable-next-line no-console
            console.warn('[CesiumMap] subscribe failed for', id, e);
          }
        }
        return () => {
          for (const s of subs) {
            try {
              s.close();
            } catch {
              /* noop */
            }
          }
        };
      }, [droneId, JSON.stringify(droneIds || []), onDroneClick]);

      // --- Viewer lifecycle: destroy on unmount ----------------------------
      useEffect(() => {
        return () => {
          const v = viewerRef.current?.cesiumElement;
          if (v && !v.isDestroyed?.()) {
            try {
              const h = (v as any).__skymasterClickHandler;
              if (h && !h.isDestroyed?.()) h.destroy();
            } catch {
              /* noop */
            }
            try {
              v.destroy();
            } catch {
              /* noop */
            }
          }
        };
      }, []);

      // --- Fly-to initial waypoint / drone ---------------------------------
      const initialTarget = React.useMemo(() => {
        if (drone) return drone;
        if (waypoints && waypoints.length > 0) {
          const w = waypoints[0];
          return { lat: w.lat, lng: w.lng, alt: w.alt ?? 100 };
        }
        return { lat: 39.9042, lng: 116.4074, alt: 500 }; // Beijing default
      }, [drone, waypoints]);

      const handleReady = (v: any) => {
        try {
          const target = initialTarget;
          v.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(
              target.lng,
              target.lat,
              (target.alt ?? 100) + 1500,
            ),
            duration: 1.2,
          });
        } catch {
          /* noop */
        }

        // Register a left-click handler that turns cartesian → cartographic
        // and reports (lat, lng) to the parent. Skips when we hit a Cesium
        // entity (the click will bubble via onDroneClick if applicable).
        try {
          const handler = new Cesium.ScreenSpaceEventHandler(v.scene.canvas);
          handler.setInputAction((movement: any) => {
            if (!onMapClick) return;
            const pickedObj = v.scene.pick(movement.position);
            if (pickedObj) return; // clicked on an entity
            const ray = v.camera.getPickRay(movement.position);
            if (!ray) return;
            const cart = v.scene.globe.pick(ray, v.scene);
            if (!cart) return;
            const carto = Cesium.Cartographic.fromCartesian(cart);
            const lat = Cesium.Math.toDegrees(carto.latitude);
            const lng = Cesium.Math.toDegrees(carto.longitude);
            onMapClick(lat, lng);
          }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
          // Store so we can clean up on unmount
          (v as any).__skymasterClickHandler = handler;
        } catch (e) {
          // eslint-disable-next-line no-console
          console.warn('[CesiumMap] click-handler setup failed', e);
        }

        onReady?.(v);
      };

      // Camera follow: keep camera on primary drone if followPrimary is set.
      useEffect(() => {
        if (!followPrimary || !drone) return;
        const v = viewerRef.current?.cesiumElement;
        if (!v || v.isDestroyed?.()) return;
        try {
          v.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(
              drone.lng,
              drone.lat,
              (drone.alt ?? 100) + 800,
            ),
            duration: 0.5,
          });
        } catch {
          /* noop */
        }
      }, [followPrimary, drone?.lat, drone?.lng]);

      // --- Build polyline positions ----------------------------------------
      const polylinePositions =
        waypoints && waypoints.length > 1
          ? Cesium.Cartesian3.fromDegreesArrayHeights(
              waypoints.flatMap((w) => [w.lng, w.lat, w.alt ?? 100]),
            )
          : undefined;

      const terrainProvider = new Cesium.EllipsoidTerrainProvider();

      return (
        <Viewer
          ref={viewerRef}
          full
          style={{ width: '100%', height: '100%' }}
          terrainProvider={terrainProvider}
          animation={false}
          baseLayerPicker={false}
          fullscreenButton={false}
          geocoder={false}
          homeButton={false}
          infoBox={false}
          sceneModePicker={false}
          selectionIndicator={false}
          timeline={false}
          navigationHelpButton={false}
          navigationInstructionsInitiallyVisible={false}
          onReady={handleReady as any}
        >
          {/* Waypoint polyline */}
          {polylinePositions && (
            <Entity>
              <PolylineGraphics
                positions={polylinePositions}
                width={3}
                material={Cesium.Color.CYAN.withAlpha(0.9)}
                clampToGround={false}
              />
            </Entity>
          )}

          {/* GeoFence zones — v2.0 compliance overlay */}
          {zones?.map((zone) => {
            const positions = Cesium.Cartesian3.fromDegreesArray(
              zone.polygon.flatMap((p) => [p[0], p[1]]),
            );
            const isNoFly = zone.kind === 'no_fly';
            const isHeight = zone.kind === 'height';
            const fill = isNoFly
              ? Cesium.Color.RED.withAlpha(0.25)
              : isHeight
              ? Cesium.Color.YELLOW.withAlpha(0.18)
              : Cesium.Color.ORANGE.withAlpha(0.20);
            const outline = isNoFly
              ? Cesium.Color.RED
              : isHeight
              ? Cesium.Color.YELLOW
              : Cesium.Color.ORANGE;
            // Label at centroid
            const cx =
              zone.polygon.reduce((a, p) => a + p[0], 0) / zone.polygon.length;
            const cy =
              zone.polygon.reduce((a, p) => a + p[1], 0) / zone.polygon.length;
            return (
              <React.Fragment key={`zone-${zone.id}`}>
                <Entity name={zone.name}>
                  <PolygonGraphics
                    hierarchy={new Cesium.PolygonHierarchy(positions)}
                    material={fill}
                    outline
                    outlineColor={outline}
                    height={0}
                  />
                </Entity>
                <Entity
                  position={Cesium.Cartesian3.fromDegrees(cx, cy, 50)}
                >
                  <LabelGraphics
                    text={
                      isHeight
                        ? `${zone.name} ≤${zone.max_alt_m}m`
                        : `⛔ ${zone.name}`
                    }
                    font="bold 12px sans-serif"
                    fillColor={Cesium.Color.WHITE}
                    showBackground
                    backgroundColor={
                      isNoFly
                        ? Cesium.Color.DARKRED.withAlpha(0.85)
                        : Cesium.Color.DARKORANGE.withAlpha(0.85)
                    }
                    pixelOffset={new Cesium.Cartesian2(0, 0)}
                    disableDepthTestDistance={Number.POSITIVE_INFINITY}
                  />
                </Entity>
              </React.Fragment>
            );
          })}

          {/* Historical trajectory trails */}
          {trails?.map((trail, tIdx) => {
            if (!trail.points || trail.points.length < 2) return null;
            const positions = Cesium.Cartesian3.fromDegreesArrayHeights(
              trail.points.flatMap((p) => [p.lng, p.lat, (p.alt ?? 100)])
            );
            // Pick a per-drone color if not provided
            const palette = [
              Cesium.Color.ORANGE, Cesium.Color.YELLOW, Cesium.Color.MAGENTA,
              Cesium.Color.SPRINGGREEN, Cesium.Color.HOTPINK,
            ];
            const color =
              (trail.color && (Cesium.Color as any)[trail.color.toUpperCase()]) ||
              palette[tIdx % palette.length];
            return (
              <Entity key={`trail-${trail.droneId}`} name={`Trail ${trail.droneId}`}>
                <PolylineGraphics
                  positions={positions}
                  width={2}
                  material={color.withAlpha(0.65)}
                  clampToGround={false}
                />
              </Entity>
            );
          })}

          {/* Numbered waypoint markers */}
          {waypoints?.map((w, idx) => {
            const seq = w.seq ?? idx + 1;
            const pos = Cesium.Cartesian3.fromDegrees(
              w.lng,
              w.lat,
              w.alt ?? 100,
            );
            return (
              <Entity key={`wp-${idx}`} position={pos} name={`WP ${seq}`}>
                <PointGraphics
                  pixelSize={12}
                  color={Cesium.Color.YELLOW}
                  outlineColor={Cesium.Color.BLACK}
                  outlineWidth={2}
                />
                <LabelGraphics
                  text={String(seq)}
                  font="12px sans-serif"
                  fillColor={Cesium.Color.WHITE}
                  showBackground
                  backgroundColor={Cesium.Color.BLACK.withAlpha(0.6)}
                  pixelOffset={new Cesium.Cartesian2(0, -22)}
                />
              </Entity>
            );
          })}

          {/* Live drone entities (fleet) — stylized 3D quadcopter model */}
          {Object.entries(fleet).map(([id, pos]) => {
            const position = Cesium.Cartesian3.fromDegrees(pos.lng, pos.lat, pos.alt);
            const isPrimary = id === primaryId;
            const bodyColor = isPrimary
              ? Cesium.Color.LIME.withAlpha(0.95)
              : Cesium.Color.CYAN.withAlpha(0.95);
            const propColor = Cesium.Color.YELLOW.withAlpha(0.9);
            // Orient body horizontally (yaw only). Cesium HeadingPitchRoll works in
            // radians. We rotate slowly for visual "spinning" feel.
            const now = Date.now() / 1000;
            const yaw = (now * 2) % (Math.PI * 2);
            const orientation = Cesium.Transforms.headingPitchRollQuaternion(
              position,
              new Cesium.HeadingPitchRoll(yaw, 0, 0),
            );
            return (
              <React.Fragment key={`drone-${id}`}>
                {/* Body */}
                <Entity
                  name={id}
                  position={position}
                  orientation={orientation}
                >
                  <BoxGraphics
                    dimensions={new Cesium.Cartesian3(6, 6, 1.5)}
                    material={bodyColor}
                    outline
                    outlineColor={Cesium.Color.BLACK.withAlpha(0.7)}
                  />
                  <LabelGraphics
                    text={id}
                    font="bold 14px sans-serif"
                    fillColor={Cesium.Color.WHITE}
                    showBackground
                    backgroundColor={
                      isPrimary
                        ? Cesium.Color.DARKGREEN.withAlpha(0.85)
                        : Cesium.Color.DARKSLATEGRAY.withAlpha(0.85)
                    }
                    pixelOffset={new Cesium.Cartesian2(0, -34)}
                    disableDepthTestDistance={Number.POSITIVE_INFINITY}
                  />
                </Entity>
                {/* Four propellers */}
                {[
                  [+3, +3],
                  [+3, -3],
                  [-3, +3],
                  [-3, -3],
                ].map(([dx, dy], i) => {
                  // Offset in ENU relative to body position.
                  const enu = Cesium.Transforms.eastNorthUpToFixedFrame(position);
                  const offset = new Cesium.Cartesian3(dx, dy, 0);
                  const propPos = Cesium.Matrix4.multiplyByPoint(
                    enu,
                    offset,
                    new Cesium.Cartesian3(),
                  );
                  return (
                    <Entity
                      key={`prop-${id}-${i}`}
                      position={propPos}
                    >
                      <CylinderGraphics
                        length={0.4}
                        topRadius={2.0}
                        bottomRadius={2.0}
                        material={propColor}
                        outline
                        outlineColor={Cesium.Color.BLACK.withAlpha(0.6)}
                      />
                    </Entity>
                  );
                })}
              </React.Fragment>
            );
          })}
        </Viewer>
      );
    };

    return CesiumMapInner;
  },
  {
    ssr: false,
    loading: () => <div>加载 3D 地图中...</div>,
  },
);

export default function CesiumMap(props: CesiumMapProps) {
  return (
    <div
      style={{
        width: '100%',
        height: props.height ?? 600,
        background: '#0b1220',
        borderRadius: 4,
        overflow: 'hidden',
      }}
    >
      <CesiumMapDynamic {...props} />
    </div>
  );
}
