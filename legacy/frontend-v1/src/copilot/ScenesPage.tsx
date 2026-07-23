import React, { useState } from 'react';
import { Plus, Import } from 'lucide-react';
import { Scene } from './types_3dgs';
import { SceneList } from './SceneList';
import { SceneDetail } from './SceneDetail';
import { CreateSceneModal } from './CreateSceneModal';
import { ImportFromMissionModal } from './ImportFromMissionModal';

interface ScenesPageProps {
  orgId: string;
}

export const ScenesPage: React.FC<ScenesPageProps> = ({ orgId }) => {
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleCreateNew = () => {
    setShowCreateModal(true);
  };

  const handleImportFromMission = () => {
    setShowImportModal(true);
  };

  const handleCreated = (sceneId: string) => {
    setShowCreateModal(false);
    setRefreshTrigger(prev => prev + 1);
    setSelectedScene(null);
  };

  const handleImported = (sceneId: string) => {
    setShowImportModal(false);
    setRefreshTrigger(prev => prev + 1);
    setSelectedScene(null);
  };

  const handleSelectScene = (scene: Scene) => {
    setSelectedScene(scene);
  };

  const handleBack = () => {
    setSelectedScene(null);
    setRefreshTrigger(prev => prev + 1);
  };

  const handleUpdate = () => {
    setRefreshTrigger(prev => prev + 1);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {selectedScene ? (
        <SceneDetail
          scene={selectedScene}
          orgId={orgId}
          onBack={handleBack}
          onUpdate={handleUpdate}
        />
      ) : (
        <div className="p-4">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-xl font-bold">3DGS 重建场景</h2>
            <div className="flex gap-2">
              <button
                onClick={handleImportFromMission}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
              >
                <Import size={16} />
                从任务导入
              </button>
              <button
                onClick={handleCreateNew}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                <Plus size={16} />
                新建场景
              </button>
            </div>
          </div>
          <SceneList
            key={refreshTrigger}
            orgId={orgId}
            onSelectScene={handleSelectScene}
            onCreateNew={handleCreateNew}
          />
        </div>
      )}

      {showCreateModal && (
        <CreateSceneModal
          orgId={orgId}
          onClose={() => setShowCreateModal(false)}
          onCreated={handleCreated}
        />
      )}

      {showImportModal && (
        <ImportFromMissionModal
          orgId={orgId}
          onClose={() => setShowImportModal(false)}
          onImported={handleImported}
        />
      )}
    </div>
  );
};

export default ScenesPage;
