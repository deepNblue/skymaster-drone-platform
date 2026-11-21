'use client';

// Ensure Cesium's asset base URL is set BEFORE importing cesium.
// Assets are expected to be copied to /public/cesium by next.config.js.
if (typeof window !== 'undefined') {
  (window as any).CESIUM_BASE_URL = (window as any).CESIUM_BASE_URL || '/cesium';
}

import React, { useEffect, useRef, useState } from 'react';
import {
  Viewer,
  Entity,
  PointGraphics,
  LabelGraphics,
  PolylineGraphics,
  BillboardGraphics,
} from 'resium';
import {
  Cartesian3,
  Color,
  EllipsoidTerrainProvider,
  HeightReference,
  LabelStyle,
  VerticalOrigin,
  Cartesian2,
  Ion,
} from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { subscribeTelemetry, TelemetryPayload } from '@/lib/ws';

// Disable Ion token requirement — we're using offline terrain
try {
  (Ion as any).defaultAccessToken = '';
} catch {
  /* noop */
}

export interface Waypoint {
  seq?: number;
  lat?: number;
  lng?: number;
  alt?: number;
  [k: string]: any;
}

export interface DroneMarker {
  droneId: string;
  lat: number;
  lng: number;
  alt?: number;
  label?: string;
}

export interface CesiumMapInnerProps {
  droneId?: string;
  droneIds?: string[];
  waypoints?: Waypoint[];
  height?: number | string;
  onReady?: (viewer: any) => void;
  onDroneClick?: (droneId: string, telemetry: TelemetryPayload) => void;
}

const terrainProvider = new EllipsoidTerrainProvider();

export default function CesiumMapInner({
  droneId,
  droneIds,
  waypoints = [],
  height = 600,
  onReady,
  onDroneClick,
}: CesiumMapInnerProps) {
  const viewerRef = useRef<any>(null);
  const flownRef = useRef<Set<string>>(new Set());
  const readyDoneRef = useRef(false);

  // Single drone telemetry
  const [singleTelemetry, setSingleTelemetry] = useState<TelemetryPayload | null>(null);
  // Multi drone telemetry map
  const [multiTelemetry, setMultiTelemetry] = useState<Record<string, TelemetryPayload>>({});

  // Subscribe: single drone
  useEffect(() => {
    if (!droneId) return;
    const sub = subscribeTelemetry(droneId, (data) => {
      setSingleTelemetry(data);
      if (
        !flownRef.current.has(droneId) &&
        typeof data.lat === 'number' &&
        typeof data.lng === 'number'
      ) {
        flyTo(data.lat, data.lng, data.alt);
        flownRef.current.add(droneId);
      }
    });
    return () => sub.close();
  }, [droneId]);

  // Subscribe: multiple drones
  useEffect(() => {
    if (!droneIds || droneIds.length === 0) return;
    const subs = droneIds.map((id) =>
      subscribeTelemetry(id, (data) => {
        setMultiTelemetry((prev) => ({ ...prev, [id]: { ...data, drone_id: id } }));
        if (
          !flownRef.current.has(id) &&
          flownRef.current.size === 0 &&
          typeof data.lat === 'number' &&
          typeof data.lng === 'number'
        ) {
          flyTo(data.lat, data.lng, data.alt);
        }
        flownRef.current.add(id);
      })
    );
    return () => subs.forEach((s) => s.close());
  }, [droneIds?.join(',')]);

  // Fly to waypoints on first load if no drone
  useEffect(() => {
    if (droneId || droneIds?.length) return;
    if (waypoints.length === 0) return;
    const w = waypoints.find((p) => p.lat != null && p.lng != null);
    if (w && w.lat != null && w.lng != null) {
      flyTo(w.lat, w.lng, w.alt);
    }
  }, [waypoints, droneId, droneIds]);

  const flyTo = (lat: number, lng: number, alt?: number) => {
    const viewer = viewerRef.current?.cesiumElement;
    if (!viewer) return;
    if (!readyDoneRef.current) {
      readyDoneRef.current = true;
      try {
        viewer.scene.globe.enableLighting = false;
        viewer.scene.skyAtmosphere.show = true;
        viewer.scene.backgroundColor = Color.fromCssColorString('#0b1220');
      } catch {
        /* noop */
      }
      if (onReady) onReady(viewer);
    }
    try {
      viewer.camera.flyTo({
        destination: Cartesian3.fromDegrees(lng, lat, Math.max(alt ? alt + 500 : 800, 800)),
        duration: 1.5,
      });
    } catch {
      /* noop */
    }
  };

  // Build waypoint polyline positions
  const polylinePositions =
    waypoints.length >= 2
      ? Cartesian3.fromDegreesArrayHeights(
          waypoints
            .filter((w) => w.lat != null && w.lng != null)
            .flatMap((w) => [w.lng as number, w.lat as number, (w.alt as number) || 0])
        )
      : undefined;

  // Aggregate drones-to-render
  const drones: DroneMarker[] = [];
  if (droneId && singleTelemetry?.lat != null && singleTelemetry?.lng != null) {
    drones.push({
      droneId,
      lat: singleTelemetry.lat as number,
      lng: singleTelemetry.lng as number,
      alt: (singleTelemetry.alt as number) || 0,
      label: droneId,
    });
  }
  if (droneIds) {
    for (const id of droneIds) {
      const t = multiTelemetry[id];
      if (t && t.lat != null && t.lng != null) {
        drones.push({
          droneId: id,
          lat: t.lat as number,
          lng: t.lng as number,
          alt: (t.alt as number) || 0,
          label: id,
        });
      }
    }
  }

  return (
    <div style={{ height, width: '100%', background: '#0b1220', position: 'relative' }}>
      <Viewer
        ref={viewerRef}
        full={false}
        style={{ height: '100%', width: '100%' }}
        terrainProvider={terrainProvider as any}
        animation={false}
        timeline={false}
        baseLayerPicker={false}
        geocoder={false}
        homeButton={false}
        navigationHelpButton={false}
        sceneModePicker={false}
        fullscreenButton={false}
        selectionIndicator={false}
        infoBox={false}
      >
        {/* Waypoint polyline */}
        {polylinePositions && (
          <Entity>
            <PolylineGraphics
              positions={polylinePositions as any}
              width={3}
              material={Color.fromCssColorString('#4dabf7')}
              clampToGround={false}
            />
          </Entity>
        )}

        {/* Waypoints as labeled points */}
        {waypoints
          .filter((w) => w.lat != null && w.lng != null)
          .map((w, i) => {
            const seq = w.seq ?? i + 1;
            const position = Cartesian3.fromDegrees(
              w.lng as number,
              w.lat as number,
              (w.alt as number) || 0
            );
            return (
              <Entity key={`wp-${i}`} position={position}>
                <PointGraphics
                  pixelSize={12}
                  color={Color.fromCssColorString('#fab005')}
                  outlineColor={Color.WHITE}
                  outlineWidth={2}
                  heightReference={HeightReference.NONE}
                />
                <LabelGraphics
                  text={`WP${seq}`}
                  font="12px sans-serif"
                  fillColor={Color.WHITE}
                  outlineColor={Color.BLACK}
                  outlineWidth={2}
                  style={LabelStyle.FILL_AND_OUTLINE}
                  verticalOrigin={VerticalOrigin.BOTTOM}
                  pixelOffset={new Cartesian2(0, -14) as any}
                />
              </Entity>
            );
          })}

        {/* Drones */}
        {drones.map((d) => {
          const position = Cartesian3.fromDegrees(d.lng, d.lat, d.alt || 0);
          return (
            <Entity
              key={`drone-${d.droneId}`}
              position={position}
              onClick={() => {
                const t =
                  d.droneId === droneId
                    ? singleTelemetry
                    : multiTelemetry[d.droneId];
                if (onDroneClick && t) onDroneClick(d.droneId, t);
              }}
            >
              <PointGraphics
                pixelSize={16}
                color={Color.fromCssColorString('#51cf66')}
                outlineColor={Color.WHITE}
                outlineWidth={2}
              />
              <LabelGraphics
                text={d.label || d.droneId}
                font="12px sans-serif"
                fillColor={Color.WHITE}
                outlineColor={Color.BLACK}
                outlineWidth={2}
                style={LabelStyle.FILL_AND_OUTLINE}
                verticalOrigin={VerticalOrigin.BOTTOM}
                pixelOffset={new Cartesian2(0, -18) as any}
              />
            </Entity>
          );
        })}
      </Viewer>
    </div>
  );
}
