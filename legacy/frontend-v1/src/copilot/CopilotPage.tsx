import React, { useState } from 'react';
import { TaskChain } from './types';
import { TaskChainList } from './TaskChainList';
import { TaskChainDetail } from './TaskChainDetail';
import { CreateChainModal } from './CreateChainModal';

interface CopilotPageProps {
  orgId: string;
}

export const CopilotPage: React.FC<CopilotPageProps> = ({ orgId }) => {
  const [selectedChain, setSelectedChain] = useState<TaskChain | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleCreateNew = () => {
    setShowCreateModal(true);
  };

  const handleCreated = (chainId: string) => {
    setShowCreateModal(false);
    // Refresh list and select the new chain
    setRefreshTrigger(prev => prev + 1);
    // The selection will happen after refresh, for simplicity we'll just close and let user click
    setSelectedChain(null);
  };

  const handleSelectChain = (chain: TaskChain) => {
    setSelectedChain(chain);
  };

  const handleBack = () => {
    setSelectedChain(null);
    setRefreshTrigger(prev => prev + 1);
  };

  const handleUpdate = () => {
    setRefreshTrigger(prev => prev + 1);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {selectedChain ? (
        <TaskChainDetail
          chain={selectedChain}
          orgId={orgId}
          onBack={handleBack}
          onUpdate={handleUpdate}
        />
      ) : (
        <TaskChainList
          key={refreshTrigger}
          orgId={orgId}
          onSelectChain={handleSelectChain}
          onCreateNew={handleCreateNew}
        />
      )}

      {showCreateModal && (
        <CreateChainModal
          orgId={orgId}
          onClose={() => setShowCreateModal(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
};

export default CopilotPage;
