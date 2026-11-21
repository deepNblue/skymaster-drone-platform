'use client';

/**
 * BBoxOverlay — canvas-based renderer for vision detections.
 *
 * Renders a semi-transparent overlay on top of a fixed-aspect video panel.
 * Detections are expected in normalized [0,1] coordinates so we don't need
 * to know the original frame resolution.
 */
import React, { useEffect, useRef } from 'react';
import type { VisionDetection } from '@/lib/useVisionStream';

const LABEL_COLORS: Record<string, string> = {
  person: '#1677ff',
  vehicle: '#13c2c2',
  car: '#13c2c2',
  truck: '#13c2c2',
  vessel: '#2f54eb',
  boat: '#2f54eb',
  fire: '#ff4d4f',
  smoke: '#fa8c16',
  crack: '#fa541c',
  solar_panel: '#faad14',
  power_line: '#722ed1',
  helmet: '#52c41a',
  default: '#8c8c8c',
};

function colorFor(label: string): string {
  return LABEL_COLORS[label] || LABEL_COLORS.default;
}

export interface BBoxOverlayProps {
  width?: number;
  height?: number;
  detections: VisionDetection[];
  showLabels?: boolean;
  minConfidence?: number;
  className?: string;
}

export function BBoxOverlay(props: BBoxOverlayProps) {
  const width = props.width ?? 640;
  const height = props.height ?? 360;
  const min = props.minConfidence ?? 0.3;
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, width, height);

    for (const d of props.detections) {
      if (d.confidence < min) continue;
      const [x0, y0, x1, y1] = d.bbox;
      const px = x0 * width;
      const py = y0 * height;
      const pw = Math.max(1, (x1 - x0) * width);
      const ph = Math.max(1, (y1 - y0) * height);
      const color = colorFor(d.label);
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.strokeRect(px, py, pw, ph);
      if (props.showLabels !== false) {
        const text = `${d.label} ${(d.confidence * 100).toFixed(0)}%`;
        ctx.font = '12px sans-serif';
        const tw = ctx.measureText(text).width + 8;
        ctx.fillStyle = color;
        ctx.fillRect(px, Math.max(0, py - 16), tw, 16);
        ctx.fillStyle = 'white';
        ctx.fillText(text, px + 4, Math.max(12, py - 4));
      }
    }
  }, [props.detections, width, height, min, props.showLabels]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className={props.className}
      style={{
        background: 'linear-gradient(135deg, #1f1f1f 0%, #262626 100%)',
        borderRadius: 6,
        border: '1px solid #303030',
      }}
    />
  );
}
