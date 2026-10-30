import { Link } from 'react-router-dom';
import { Network, ArrowDownRight, ArrowUpLeft } from 'lucide-react';

const STATUS_STYLES = {
  completed: 'bg-green-900/40 text-green-300 border-green-700',
  failed: 'bg-red-900/40 text-red-300 border-red-700',
  missing_packages: 'bg-red-900/40 text-red-300 border-red-700',
  building: 'bg-blue-900/40 text-blue-300 border-blue-700',
  fixing: 'bg-purple-900/40 text-purple-300 border-purple-700',
  pending: 'bg-yellow-900/40 text-yellow-300 border-yellow-700',
  dep_build_pending: 'bg-yellow-900/40 text-yellow-300 border-yellow-700',
  waiting_for_deps: 'bg-orange-900/40 text-orange-300 border-orange-700',
  not_built: 'bg-gray-700/60 text-gray-300 border-gray-600',
};

const TYPE_LABELS = { build: 'build', runtime: 'runtime', both: 'build+runtime' };

function DependencyRow({ id, name, version, buildStatus, type, constraint }) {
  return (
    <Link
      to={`/packages/${id}`}
      className="flex items-center justify-between gap-2 text-sm py-1.5 px-2 bg-gray-700/30 hover:bg-gray-700/60 rounded transition-colors"
    >
      <div className="min-w-0 flex items-baseline gap-2">
        <span className="text-blue-300 truncate">{name}</span>
        {version && <span className="text-xs text-gray-500">{version}</span>}
        {constraint && <span className="text-xs text-gray-400 font-mono">{constraint}</span>}
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <span className="text-xs text-gray-500">{TYPE_LABELS[type] || type}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded border ${STATUS_STYLES[buildStatus] || STATUS_STYLES.not_built}`}
        >
          {(buildStatus || 'not_built').replace(/_/g, ' ')}
        </span>
      </div>
    </Link>
  );
}

function DependencyColumn({ title, icon: Icon, items, emptyText }) {
  return (
    <div>
      <h3 className="text-sm font-medium text-gray-400 mb-3 flex items-center gap-1.5">
        <Icon className="h-4 w-4" />
        {title} ({items.length})
      </h3>
      {items.length === 0 ? (
        <p className="text-sm text-gray-500 italic">{emptyText}</p>
      ) : (
        <div className="space-y-1 max-h-80 overflow-y-auto pr-1">
          {items.map(({ key, ...item }) => (
            <DependencyRow key={key} {...item} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function PackageDependencies({ dependencies }) {
  const dependsOn = (dependencies?.depends_on || []).map((d) => ({
    key: d.id,
    id: d.depends_on,
    name: d.depends_on_name,
    version: d.depends_on_version,
    buildStatus: d.depends_on_build_status,
    type: d.dependency_type,
    constraint: d.version_constraint,
  }));
  const requiredBy = (dependencies?.required_by || []).map((d) => ({
    key: d.id,
    id: d.package,
    name: d.package_name,
    version: d.package_version,
    buildStatus: d.package_build_status,
    type: d.dependency_type,
    constraint: d.version_constraint,
  }));

  return (
    <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
      <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <Network className="h-5 w-5" />
        Dependencies
      </h2>
      {!dependencies ? (
        <p className="text-sm text-gray-500">Loading dependencies...</p>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <DependencyColumn
            title="Depends on"
            icon={ArrowDownRight}
            items={dependsOn}
            emptyText="This package has no tracked dependencies."
          />
          <DependencyColumn
            title="Required by"
            icon={ArrowUpLeft}
            items={requiredBy}
            emptyText="No tracked packages depend on this package."
          />
        </div>
      )}
    </div>
  );
}
