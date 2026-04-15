import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, RotateCcw } from 'lucide-react';
import { useMemo, useCallback, useEffect, memo } from 'react';
import { projectsAPI } from '../lib/api';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
  MarkerType,
  Handle,
  Position,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

// ─── Constants ───────────────────────────────────────────────────────────────
const NODE_W = 180;
const NODE_H = 56;
const H_GAP  = 80;
const V_GAP  = 16;
const PAD    = 40;

const STATUS_STYLE = {
  completed:         { bg: '#052e16', border: '#22c55e', text: '#4ade80' },
  building:          { bg: '#0c1a2e', border: '#3b82f6', text: '#60a5fa' },
  pending:           { bg: '#1c2432', border: '#6b7280', text: '#9ca3af' },
  failed:            { bg: '#3b0000', border: '#ef4444', text: '#f87171' },
  not_built:         { bg: '#111827', border: '#374151', text: '#6b7280' },
  waiting_for_deps:  { bg: '#13113a', border: '#818cf8', text: '#a5b4fc' },
  dep_build_pending: { bg: '#1c1500', border: '#ca8a04', text: '#fbbf24' },
  missing_packages:  { bg: '#200a0a', border: '#dc2626', text: '#fca5a5' },
};

const LEGEND = [
  ['not_built', 'Not Built'], ['pending', 'Pending'], ['building', 'Building'],
  ['waiting_for_deps', 'Waiting Deps'], ['dep_build_pending', 'Dep Pending'],
  ['completed', 'Completed'], ['failed', 'Failed'], ['missing_packages', 'Missing Pkgs'],
];

// ─── Custom node ─────────────────────────────────────────────────────────────
const PackageNode = memo(({ data, selected }) => {
  const s    = STATUS_STYLE[data.build_status] || STATUS_STYLE.not_built;
  const name = data.name.length > 22 ? data.name.slice(0, 20) + '…' : data.name;
  const ver  = (data.version || '').length > 19 ? data.version.slice(0, 17) + '…' : data.version;
  return (
    <div
      title={`${data.name}  ${data.version}  ·  ${(data.build_status || '').replace(/_/g, ' ')}`}
      style={{
        width: NODE_W, height: NODE_H,
        background: s.bg,
        border: `${selected ? 2.5 : 1.5}px solid ${selected ? '#e5e7eb' : s.border}`,
        borderRadius: 6, overflow: 'hidden', position: 'relative',
        display: 'flex', alignItems: 'center',
        paddingLeft: data.is_direct_dependency ? 14 : 9,
        boxShadow: selected ? '0 0 0 3px rgba(255,255,255,0.1)' : 'none',
      }}
    >
      {data.is_direct_dependency && (
        <div style={{ position: 'absolute', left: 0, top: 0, width: 4, height: '100%', background: '#818cf8', opacity: 0.85 }} />
      )}
      <div style={{ overflow: 'hidden' }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: s.text, fontFamily: "ui-monospace,'Courier New',monospace", lineHeight: 1.2, whiteSpace: 'nowrap' }}>{name}</div>
        <div style={{ fontSize: 10, color: '#6b7280', fontFamily: "ui-monospace,'Courier New',monospace", lineHeight: 1.2, whiteSpace: 'nowrap', marginTop: 3 }}>{ver}</div>
      </div>
      <Handle type="target" position={Position.Left}  style={{ background: s.border, width: 7, height: 7, border: 'none' }} />
      <Handle type="source" position={Position.Right} style={{ background: s.border, width: 7, height: 7, border: 'none' }} />
    </div>
  );
});
PackageNode.displayName = 'PackageNode';

const nodeTypes = { package: PackageNode };

// ─── BFS layout → React Flow graph ───────────────────────────────────────────
function buildFlowGraph(packages) {
  if (!packages?.length) return { rfNodes: [], rfEdges: [] };

  const byName = {};
  packages.forEach(p => { byName[p.name] = p; });

  // Build raw edges + forward-adjacency map
  const rawEdges = [];
  const adjFwd   = {};
  packages.forEach(pkg => {
    (pkg.dependent_packages || []).forEach(depName => {
      if (!byName[depName]) return;
      rawEdges.push({ src: depName, tgt: pkg.name });
      (adjFwd[depName] = adjFwd[depName] || []).push(pkg.name);
    });
  });

  // BFS shortest-path from direct deps
  const dist  = {};
  const queue = [];
  packages.forEach(p => {
    if (p.is_direct_dependency) { dist[p.name] = 0; queue.push(p.name); }
  });
  let qi = 0;
  while (qi < queue.length) {
    const name = queue[qi++];
    (adjFwd[name] || []).forEach(next => {
      if (dist[next] === undefined) { dist[next] = dist[name] + 1; queue.push(next); }
    });
  }
  packages.forEach(p => { if (dist[p.name] === undefined) dist[p.name] = 0; });

  // Assign column positions
  const cols = {};
  packages.forEach(p => { (cols[dist[p.name]] = cols[dist[p.name]] || []).push(p); });
  Object.values(cols).forEach(arr => arr.sort((a, b) => a.name.localeCompare(b.name)));

  const colKeys  = Object.keys(cols).map(Number).sort((a, b) => a - b);
  const maxCount = Math.max(...Object.values(cols).map(a => a.length));

  const pos = {};
  colKeys.forEach(d => {
    const pkgs   = cols[d];
    const x      = PAD + d * (NODE_W + H_GAP);
    const colH   = pkgs.length * (NODE_H + V_GAP) - V_GAP;
    const totalH = maxCount * (NODE_H + V_GAP) - V_GAP;
    const startY = PAD + (totalH - colH) / 2;
    pkgs.forEach((p, i) => { pos[p.name] = { x, y: startY + i * (NODE_H + V_GAP) }; });
  });

  const rfNodes = packages.map(p => ({
    id:       String(p.id),
    type:     'package',
    position: pos[p.name] ?? { x: PAD, y: PAD },
    data: {
      name:                 p.name,
      version:              p.version || '',
      build_status:         p.build_status || 'not_built',
      is_direct_dependency: p.is_direct_dependency,
      pkgId:                p.id,
    },
    width:  NODE_W,
    height: NODE_H,
  }));

  const rfEdges = rawEdges.map((e, i) => ({
    id:        `e${i}`,
    source:    String(byName[e.src].id),
    target:    String(byName[e.tgt].id),
    type:      'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: '#4b5563' },
    style:     { stroke: '#374151', strokeWidth: 1.5, opacity: 0.7 },
  }));

  return { rfNodes, rfEdges };
}

// ─── Inner flow component (useReactFlow requires a ReactFlowProvider parent) ─
function FlowInner({ project, packagesData, isLoading, id, navigate }) {
  const allPackages = useMemo(() => packagesData?.packages || [], [packagesData]);
  const { rfNodes: initNodes, rfEdges: initEdges } = useMemo(
    () => buildFlowGraph(allPackages),
    [allPackages],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initEdges);
  const { fitView } = useReactFlow();

  // Sync whenever package data changes
  useEffect(() => {
    setNodes(initNodes);
    setEdges(initEdges);
    if (initNodes.length) setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 60);
  }, [initNodes, initEdges, setNodes, setEdges, fitView]);

  const resetLayout = useCallback(() => {
    setNodes(initNodes);
    setEdges(initEdges);
    setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 60);
  }, [initNodes, initEdges, setNodes, setEdges, fitView]);

  const onNodeClick = useCallback((_, node) => {
    navigate(`/packages/${node.data.pkgId}`);
  }, [navigate]);

  return (
    <div className="flex flex-col bg-gray-900" style={{ height: '100vh' }}>

      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 bg-gray-800 border-b border-gray-700 flex-shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate(`/projects/${id}`)}
            className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
            title="Back to project"
          >
            <ArrowLeft className="h-5 w-5 text-gray-300" />
          </button>
          <div>
            <h1 className="text-base font-semibold text-white">Dependency Map</h1>
            {project && <p className="text-xs text-gray-400">{project.name}</p>}
          </div>
        </div>

        <div className="flex items-center gap-5 text-xs text-gray-400">
          <span><span className="text-white font-medium">{packagesData?.direct_count ?? 0}</span> direct</span>
          <span><span className="text-white font-medium">{packagesData?.transitive_count ?? 0}</span> transitive</span>
          <span><span className="text-white font-medium">{edges.length}</span> edges</span>
        </div>

        <button
          onClick={resetLayout}
          title="Reset to auto-layout"
          className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-gray-700 rounded-lg transition-colors text-amber-400 hover:text-amber-300"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Reset layout
        </button>
      </div>

      {/* Legend */}
      <div className="flex items-center flex-wrap gap-x-4 gap-y-1 px-6 py-2 bg-gray-800/50 border-b border-gray-700/40 flex-shrink-0">
        {LEGEND.map(([status, label]) => {
          const s = STATUS_STYLE[status] || STATUS_STYLE.not_built;
          return (
            <div key={status} className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded" style={{ background: s.bg, border: `1.5px solid ${s.border}` }} />
              <span className="text-xs text-gray-400">{label}</span>
            </div>
          );
        })}
        <div className="flex items-center gap-1.5 ml-2">
          <div className="w-1 h-3 rounded" style={{ background: '#818cf8' }} />
          <span className="text-xs text-gray-400">Direct dep</span>
        </div>
        <span className="ml-auto text-xs text-gray-600 hidden sm:block">
          Drag nodes · Scroll to zoom · Click to open
        </span>
      </div>

      {/* Canvas */}
      <div className="flex-1 relative">
        {isLoading ? (
          <div className="flex items-center justify-center h-full">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500" />
          </div>
        ) : nodes.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-gray-500 text-sm">
            <p>No packages found for this project.</p>
            <p>Resolve dependencies on the project page first.</p>
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            minZoom={0.04}
            maxZoom={4}
            colorMode="dark"
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#1e2330" gap={24} size={1} />
            <Controls
              showInteractive={false}
              style={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 8 }}
            />
            <MiniMap
              nodeColor={(n) => (STATUS_STYLE[n.data?.build_status] || STATUS_STYLE.not_built).border}
              maskColor="rgba(0,0,0,0.65)"
              style={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
            />
          </ReactFlow>
        )}
      </div>
    </div>
  );
}

// ─── Outer component ─────────────────────────────────────────────────────────
export default function DependencyMap() {
  const { id }   = useParams();
  const navigate = useNavigate();

  const { data: project } = useQuery({
    queryKey: ['project', id],
    queryFn:  async () => (await projectsAPI.get(id)).data,
  });

  const { data: packagesData, isLoading } = useQuery({
    queryKey: ['project-packages', id],
    queryFn:  async () => (await projectsAPI.packages(id)).data,
    enabled:  !!id,
  });

  return (
    <ReactFlowProvider>
      <FlowInner
        project={project}
        packagesData={packagesData}
        isLoading={isLoading}
        id={id}
        navigate={navigate}
      />
    </ReactFlowProvider>
  );
}

