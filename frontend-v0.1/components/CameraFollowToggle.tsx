'use client';

import React, { useState } from 'react';
import { Button, Tooltip } from 'antd';
import { AimOutlined } from '@ant-design/icons';

interface Props {
  followId?: string;
  onToggle: (following: boolean) => void;
}

/** Small floating "follow camera" toggle. */
export default function CameraFollowToggle({ followId, onToggle }: Props) {
  const [following, setFollowing] = useState(false);

  return (
    <Tooltip title={following ? '关闭相机跟随' : `相机跟随 ${followId || 'primary drone'}`}>
      <Button
        type={following ? 'primary' : 'default'}
        icon={<AimOutlined />}
        onClick={() => {
          const next = !following;
          setFollowing(next);
          onToggle(next);
        }}
        style={{
          position: 'absolute',
          top: 16,
          left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 20,
          background: following ? undefined : 'rgba(13, 17, 23, 0.9)',
          border: '1px solid #21262d',
          color: following ? undefined : '#e6edf3',
        }}
      >
        {following ? '相机跟随中' : '跟随相机'}
      </Button>
    </Tooltip>
  );
}
