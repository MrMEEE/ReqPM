import { useRef, useState } from 'react';
import { packagesAPI } from '../lib/api';

export default function VersionDropdown({ packageId, currentVersion, onVersionChange, toast, disabled = false }) {
  const [isOpen, setIsOpen] = useState(false);
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [dropdownStyle, setDropdownStyle] = useState({});
  const buttonRef = useRef(null);

  const handleClick = async () => {
    if (!isOpen) {
      if (buttonRef.current) {
        const rect = buttonRef.current.getBoundingClientRect();
        setDropdownStyle({ top: rect.bottom + 4, left: rect.left });
      }
      if (versions.length === 0) {
        setLoading(true);
        try {
          const response = await packagesAPI.getVersions(packageId);
          setVersions(response.data.versions || []);
        } catch (error) {
          console.error('Failed to fetch versions:', error);
          toast.error('Failed to fetch versions');
        } finally {
          setLoading(false);
        }
      }
    }
    setIsOpen(!isOpen);
  };

  const handleVersionSelect = (version) => {
    setIsOpen(false);
    if (version !== currentVersion) {
      onVersionChange(packageId, version);
    }
  };

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        onClick={handleClick}
        className="text-blue-400 hover:text-blue-300 underline text-sm"
        disabled={loading || disabled}
        title={disabled ? undefined : 'Change version'}
      >
        {loading ? 'Loading...' : currentVersion}
      </button>
      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-[999]"
            onClick={() => setIsOpen(false)}
          />
          <div
            className="fixed z-[1000] w-32 bg-gray-700 border border-gray-600 rounded-md shadow-lg max-h-60 overflow-auto flex flex-col"
            style={dropdownStyle}
          >
            {versions.length === 0 ? (
              <div className="px-3 py-2 text-sm text-gray-400">No versions</div>
            ) : (
              versions.map((version) => (
                <button
                  key={version}
                  onClick={() => handleVersionSelect(version)}
                  className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-600 ${
                    version === currentVersion ? 'bg-gray-600 text-white' : 'text-gray-200'
                  }`}
                >
                  {version}
                </button>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
