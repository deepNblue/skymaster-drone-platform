'use client';

/**
 * HlsPlayer — minimal HLS.js / native HLS video element.
 *
 * Extracted from the legacy /dashboard/streams page so the video wall can
 * reuse it. Reports a coarse player state up to the parent so tiles can
 * show loading / playing / error overlays. Supports a `retryKey` prop:
 * bumping it tears down and re-attaches the media source (used by the
 * "重连" button).
 */
import { useEffect, useRef, useState } from 'react';

export type PlayerState = 'idle' | 'loading' | 'playing' | 'error';

export interface HlsPlayerProps {
  src: string;
  /** Bump to force a full reconnect (destroy + reload). */
  retryKey?: number;
  /** Muted + playsInline by default so autoplay is allowed by browsers. */
  muted?: boolean;
  onStateChange?: (state: PlayerState) => void;
  className?: string;
  style?: React.CSSProperties;
}

export default function HlsPlayer({
  src,
  retryKey = 0,
  muted = true,
  onStateChange,
  className,
  style,
}: HlsPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [nativeOk, setNativeOk] = useState<boolean | null>(null);
  const onStateRef = useRef(onStateChange);
  onStateRef.current = onStateChange;

  useEffect(() => {
    let cancelled = false;
    let hls: import('hls.js').default | null = null;
    const video = videoRef.current;
    if (!video) return;

    const report = (s: PlayerState) => onStateRef.current?.(s);
    report('loading');

    const canNative =
      video.canPlayType('application/vnd.apple.mpegurl') !== '';
    setNativeOk(canNative);

    const onPlaying = () => report('playing');
    const onWaiting = () => report('loading');
    const onError = () => report('error');
    video.addEventListener('playing', onPlaying);
    video.addEventListener('waiting', onWaiting);
    video.addEventListener('error', onError);

    if (canNative) {
      video.src = src;
      // Some browsers (Safari) won't fire 'playing' without play().
      video.play().catch(() => {
        /* autoplay may be blocked; user can press play */
      });
    } else {
      import('hls.js')
        .then((mod) => {
          if (cancelled) return;
          const Hls = mod.default;
          if (Hls && Hls.isSupported()) {
            hls = new Hls({
              // Wall mode: low latency is nicer than seeking efficiency.
              liveDurationInfinity: true,
              lowLatencyMode: true,
              maxBufferLength: 6,
            });
            hls.loadSource(src);
            hls.attachMedia(video);
            hls.on(Hls.Events.ERROR, (_evt, data) => {
              if (data?.fatal) report('error');
            });
            video.play().catch(() => {
              /* autoplay may be blocked */
            });
          } else {
            video.src = src;
          }
        })
        .catch(() => {
          if (!cancelled) {
            video.src = src;
          }
        });
    }

    return () => {
      cancelled = true;
      video.removeEventListener('playing', onPlaying);
      video.removeEventListener('waiting', onWaiting);
      video.removeEventListener('error', onError);
      if (hls) {
        try {
          hls.destroy();
        } catch {
          /* noop */
        }
        hls = null;
      }
      try {
        video.removeAttribute('src');
        video.load();
      } catch {
        /* noop */
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, retryKey]);

  return (
    <video
      ref={videoRef}
      className={className}
      style={
        style ?? {
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          background: '#000',
        }
      }
      muted={muted}
      playsInline
      autoPlay
      controls={false}
      data-native-hls={nativeOk === null ? undefined : nativeOk ? '1' : '0'}
    />
  );
}
