import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useSession } from "../state";
import { pickText } from "./Bits";
import type { Key } from "../i18n";

export interface GraphNode {
  id: number;
  type: string;
  labels: Record<string, string>;
  description: string | null;
  item_ids: number[];
}

export interface GraphEdge {
  id: number;
  from: number;
  to: number;
  relation: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

interface SimNode extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  degree: number;
  pinned?: boolean;
}

const TYPE_THEME: Record<string, { color: string; bg: string; border: string }> = {
  person: { color: "#1b2a6b", bg: "#e8ecf8", border: "#1b2a6b" },
  organisation: { color: "#1f6b45", bg: "#e6f4ea", border: "#1f6b45" },
  place: { color: "#6b5214", bg: "#f6efdc", border: "#c9a24a" },
  event: { color: "#8b263e", bg: "#fce8ed", border: "#8b263e" },
  concept: { color: "#3b4256", bg: "#edf0f7", border: "#4a5268" },
  document: { color: "#0f5b78", bg: "#e6f6fc", border: "#0f5b78" },
};

const DEFAULT_THEME = { color: "#4a5268", bg: "#eef1f7", border: "#c9cfdd" };

export function getNodeColor(type: string) {
  const t = TYPE_THEME[type] || DEFAULT_THEME;
  return { bg: t.color, border: t.border, fill: t.bg, text: t.color };
}

const TYPE_ORDER = ["person", "organisation", "place", "event", "concept", "document"];

const DEFAULT_ZOOM = 0.9;

export interface GraphViewProps {
  data: GraphData;
  selectedId: number | null;
  onSelectNode: (id: number | null) => void;
}

export function GraphView({ data, selectedId, onSelectNode }: GraphViewProps) {
  const { lang, t } = useSession();
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const [search, setSearch] = useState("");
  const [activeTypeFilter, setActiveTypeFilter] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [isPanning, setIsPanning] = useState(false);

  // Viewport transform (Pan & Zoom) - fitted by default
  const [dimensions, setDimensions] = useState({ width: 1100, height: 560 });
  const [transform, setTransform] = useState(() => ({
    k: DEFAULT_ZOOM,
    x: (1100 / 2) * (1 - DEFAULT_ZOOM),
    y: (560 / 2) * (1 - DEFAULT_ZOOM),
  }));

  const simNodesRef = useRef<SimNode[]>([]);
  const simEdgesRef = useRef<GraphEdge[]>([]);
  const [renderCounter, setRenderCounter] = useState(0);

  // Pointer interaction state
  const dragRef = useRef<{
    nodeId: number | null;
    isPanning: boolean;
    startX: number;
    startY: number;
    startTransformX: number;
    startTransformY: number;
    moved: boolean;
  }>({
    nodeId: null,
    isPanning: false,
    startX: 0,
    startY: 0,
    startTransformX: 0,
    startTransformY: 0,
    moved: false,
  });

  // Calculate degrees for node importance
  const degrees = useMemo(() => {
    const degMap = new Map<number, number>();
    for (const n of data.nodes) degMap.set(n.id, 0);
    for (const e of data.edges) {
      degMap.set(e.from, (degMap.get(e.from) ?? 0) + 1);
      degMap.set(e.to, (degMap.get(e.to) ?? 0) + 1);
    }
    return degMap;
  }, [data]);

  // Update dimensions on container resize & initialize centered zoomed view
  useEffect(() => {
    let initialized = false;
    const updateSize = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        if (rect.width > 0) {
          const w = Math.max(rect.width, 600);
          const h = Math.max(Math.min(window.innerHeight * 0.62, 560), 440);
          setDimensions({ width: w, height: h });
          if (!initialized) {
            initialized = true;
            setTransform({
              k: DEFAULT_ZOOM,
              x: (w / 2) * (1 - DEFAULT_ZOOM),
              y: (h / 2) * (1 - DEFAULT_ZOOM),
            });
          }
        }
      }
    };
    updateSize();
    window.addEventListener("resize", updateSize);
    return () => window.removeEventListener("resize", updateSize);
  }, []);

  // Compute clean, widely-spaced initial layout by categories
  useEffect(() => {
    if (!data.nodes.length) return;
    const W = dimensions.width;
    const H = dimensions.height;
    const cx = W / 2;
    const cy = H / 2;

    const groups = new Map<string, GraphNode[]>();
    for (const n of data.nodes) {
      groups.set(n.type, [...(groups.get(n.type) ?? []), n]);
    }
    const types = [...groups.keys()].sort((a, b) => TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b));

    const initialNodes: SimNode[] = [];
    types.forEach((type, gi) => {
      const typeNodes = groups.get(type)!;
      const baseAngle = (gi / types.length) * Math.PI * 2 - Math.PI / 2;
      const span = (Math.PI * 2) / types.length;

      typeNodes.forEach((node, i) => {
        const existing = simNodesRef.current.find((n) => n.id === node.id);
        const deg = degrees.get(node.id) ?? 0;
        const radius = node.type === "person" ? 15 : 12 + Math.min(deg, 4);

        if (existing) {
          initialNodes.push({
            ...node,
            x: existing.x,
            y: existing.y,
            vx: existing.vx,
            vy: existing.vy,
            radius,
            degree: deg,
            pinned: existing.pinned,
          });
        } else {
          // Generous radial spacing so nodes are spread apart
          const a = baseAngle + span * ((i + 0.5) / typeNodes.length) * 0.88;
          const r = 260 + (i % 3) * 110;
          initialNodes.push({
            ...node,
            x: cx + Math.cos(a) * r * 1.6,
            y: cy + Math.sin(a) * r * 1.15,
            vx: 0,
            vy: 0,
            radius,
            degree: deg,
          });
        }
      });
    });

    simNodesRef.current = initialNodes;
    simEdgesRef.current = data.edges;
    setRenderCounter((c) => c + 1);
  }, [data, dimensions, degrees]);

  // Gentle physics relaxer with spacious node repulsion
  const animFrameRef = useRef<number | null>(null);
  const alphaRef = useRef(0.25);

  const triggerSimulation = useCallback((alpha = 0.3) => {
    alphaRef.current = Math.max(alphaRef.current, alpha);
  }, []);

  useEffect(() => {
    let lastTime = performance.now();

    const tick = (now: number) => {
      const dt = Math.min((now - lastTime) / 1000, 0.05);
      lastTime = now;

      const nodes = simNodesRef.current;
      const edges = simEdgesRef.current;
      const alpha = alphaRef.current;

      if (nodes.length > 0 && alpha > 0.002) {
        const cx = dimensions.width / 2;
        const cy = dimensions.height / 2;

        // Subtle center anchor (low gravity so nodes remain spaced apart)
        for (const n of nodes) {
          if (n.pinned) continue;
          n.vx += (cx - n.x) * 0.05 * alpha * dt;
          n.vy += (cy - n.y) * 0.05 * alpha * dt;
        }

        // Strong electrostatic repulsion and collision padding
        for (let i = 0; i < nodes.length; i++) {
          const n1 = nodes[i];
          for (let j = i + 1; j < nodes.length; j++) {
            const n2 = nodes[j];
            const dx = n2.x - n1.x;
            const dy = n2.y - n1.y;
            const distSq = dx * dx + dy * dy + 1200;
            const dist = Math.sqrt(distSq);

            // Wide area repulsion
            const force = (58000 * alpha * dt) / distSq;
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;

            if (!n1.pinned) {
              n1.vx -= fx;
              n1.vy -= fy;
            }
            if (!n2.pinned) {
              n2.vx += fx;
              n2.vy += fy;
            }

            // Hard collision separation so labels and circles never overlap
            const minSeparation = n1.radius + n2.radius + 80;
            if (dist < minSeparation && dist > 0) {
              const push = ((minSeparation - dist) / minSeparation) * 50 * alpha * dt;
              const px = (dx / dist) * push;
              const py = (dy / dist) * push;
              if (!n1.pinned) {
                n1.vx -= px;
                n1.vy -= py;
              }
              if (!n2.pinned) {
                n2.vx += px;
                n2.vy += py;
              }
            }
          }
        }

        // Springs along edges (long rest length for breathing room)
        const nodeMap = new Map(nodes.map((n) => [n.id, n]));
        const restLength = 220;
        for (const e of edges) {
          const s = nodeMap.get(e.from);
          const tr = nodeMap.get(e.to);
          if (!s || !tr) continue;
          const dx = tr.x - s.x;
          const dy = tr.y - s.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = (dist - restLength) * 1.8 * alpha * dt;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;

          if (!s.pinned) {
            s.vx += fx;
            s.vy += fy;
          }
          if (!tr.pinned) {
            tr.vx -= fx;
            tr.vy -= fy;
          }
        }

        // Damping
        for (const n of nodes) {
          if (n.pinned) continue;
          n.vx *= 0.88;
          n.vy *= 0.88;
          n.x += n.vx * dt * 60;
          n.y += n.vy * dt * 60;
        }

        alphaRef.current *= 0.985;
        setRenderCounter((c) => (c + 1) % 1000000);
      }

      animFrameRef.current = requestAnimationFrame(tick);
    };

    animFrameRef.current = requestAnimationFrame(tick);
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [dimensions]);

  // Connected neighbors
  const activeFocusId = hoveredId ?? selectedId;
  const connectedNodeIds = useMemo(() => {
    if (activeFocusId === null) return new Set<number>();
    const neighbors = new Set<number>([activeFocusId]);
    for (const e of data.edges) {
      if (e.from === activeFocusId) neighbors.add(e.to);
      if (e.to === activeFocusId) neighbors.add(e.from);
    }
    return neighbors;
  }, [activeFocusId, data.edges]);

  // Viewport Zoom & Pan
  const handleZoom = (delta: number) => {
    setTransform((prev) => {
      const newK = Math.max(0.4, Math.min(prev.k * delta, 2.5));
      const factor = newK / prev.k;
      const cx = dimensions.width / 2;
      const cy = dimensions.height / 2;
      return {
        k: newK,
        x: cx - (cx - prev.x) * factor,
        y: cy - (cy - prev.y) * factor,
      };
    });
  };

  const handleResetView = () => {
    const cx = dimensions.width / 2;
    const cy = dimensions.height / 2;
    setTransform({
      k: DEFAULT_ZOOM,
      x: cx * (1 - DEFAULT_ZOOM),
      y: cy * (1 - DEFAULT_ZOOM),
    });
    triggerSimulation(0.3);
  };

  // Pointer drag & pan
  const handlePointerDown = (e: React.PointerEvent) => {
    const target = e.target as HTMLElement | SVGElement;
    const nodeG = target.closest<SVGGElement>("[data-node-id]");

    try {
      (e.currentTarget as Element).setPointerCapture(e.pointerId);
    } catch {
      // Ignored if pointer capture is unsupported
    }

    if (nodeG) {
      const nodeId = Number(nodeG.getAttribute("data-node-id"));
      const node = simNodesRef.current.find((n) => n.id === nodeId);
      if (node) {
        node.pinned = true;
        dragRef.current = {
          nodeId,
          isPanning: false,
          startX: e.clientX,
          startY: e.clientY,
          startTransformX: transform.x,
          startTransformY: transform.y,
          moved: false,
        };
      }
    } else {
      setIsPanning(true);
      dragRef.current = {
        nodeId: null,
        isPanning: true,
        startX: e.clientX,
        startY: e.clientY,
        startTransformX: transform.x,
        startTransformY: transform.y,
        moved: false,
      };
    }
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    const distMoved = Math.hypot(e.clientX - dragRef.current.startX, e.clientY - dragRef.current.startY);
    if (distMoved > 3) {
      dragRef.current.moved = true;
    }

    if (dragRef.current.nodeId !== null) {
      const node = simNodesRef.current.find((n) => n.id === dragRef.current.nodeId);
      if (node) {
        const dx = (e.clientX - dragRef.current.startX) / transform.k;
        const dy = (e.clientY - dragRef.current.startY) / transform.k;
        node.x += dx;
        node.y += dy;
        node.vx = 0;
        node.vy = 0;
        dragRef.current.startX = e.clientX;
        dragRef.current.startY = e.clientY;
        triggerSimulation(0.3);
        setRenderCounter((c) => (c + 1) % 1000000);
      }
    } else if (dragRef.current.isPanning) {
      const dx = e.clientX - dragRef.current.startX;
      const dy = e.clientY - dragRef.current.startY;
      setTransform((prev) => ({
        ...prev,
        x: dragRef.current.startTransformX + dx,
        y: dragRef.current.startTransformY + dy,
      }));
    }
  };

  const handlePointerUp = (e: React.PointerEvent) => {
    try {
      if ((e.currentTarget as Element).hasPointerCapture(e.pointerId)) {
        (e.currentTarget as Element).releasePointerCapture(e.pointerId);
      }
    } catch {
      // Ignored
    }

    const { nodeId, moved } = dragRef.current;

    if (nodeId !== null) {
      const node = simNodesRef.current.find((n) => n.id === nodeId);
      if (node) node.pinned = false;
      // If it was a quick click without dragging, handle selection
      if (!moved) {
        onSelectNode(selectedId === nodeId ? null : nodeId);
        triggerSimulation(0.2);
      }
      dragRef.current.nodeId = null;
      triggerSimulation(0.2);
    } else if (!moved && dragRef.current.isPanning) {
      // Clicked on empty canvas background without panning: clear selection
      onSelectNode(null);
    }

    dragRef.current.isPanning = false;
    dragRef.current.moved = false;
    setIsPanning(false);
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92;
    if (svgRef.current) {
      const rect = svgRef.current.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      setTransform((prev) => {
        const newK = Math.max(0.4, Math.min(prev.k * zoomFactor, 2.5));
        const factor = newK / prev.k;
        return {
          k: newK,
          x: mouseX - (mouseX - prev.x) * factor,
          y: mouseY - (mouseY - prev.y) * factor,
        };
      });
    }
  };

  // Node filtering
  const matchingNodeIds = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return null;
    const matches = new Set<number>();
    for (const n of data.nodes) {
      const label = pickText(n.labels, lang).toLowerCase();
      const desc = (n.description ?? "").toLowerCase();
      if (label.includes(q) || desc.includes(q)) {
        matches.add(n.id);
      }
    }
    return matches;
  }, [search, data.nodes, lang]);

  const nodes = simNodesRef.current;
  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes, renderCounter]);

  const availableTypes = useMemo(() => {
    const s = new Set<string>();
    for (const n of data.nodes) s.add(n.type);
    return Array.from(s).sort((a, b) => TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b));
  }, [data.nodes]);

  return (
    <div className="heritage-graph-container" ref={containerRef}>
      {/* Top Header Bar with Filter Pills and Zoom Controls */}
      <div className="heritage-graph-toolbar">
        <div className="heritage-toolbar-left">
          <div className="heritage-search-box">
            <input
              type="text"
              placeholder={t("graphSearchPlaceholder")}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                triggerSimulation(0.3);
              }}
              className="heritage-graph-search-input"
              aria-label={t("graphSearchLabel")}
            />
            {search && (
              <button
                type="button"
                className="heritage-search-clear"
                onClick={() => setSearch("")}
                aria-label={t("clearSearch")}
              >
                ✕
              </button>
            )}
          </div>

          <div className="heritage-filter-chips">
            {availableTypes.map((type) => {
              const count = data.nodes.filter((n) => n.type === type).length;
              const theme = TYPE_THEME[type] || DEFAULT_THEME;
              const isActive = activeTypeFilter === type;
              return (
                <button
                  key={type}
                  type="button"
                  className={`chip-link heritage-filter-chip ${isActive ? "active" : ""}`}
                  onClick={() => {
                    setActiveTypeFilter(isActive ? null : type);
                    triggerSimulation(0.3);
                  }}
                  aria-pressed={isActive}
                >
                  <span className="heritage-chip-dot" style={{ backgroundColor: theme.color }} />
                  <span>{t(`node_${type}` as Key)}</span>
                  <span className="heritage-chip-count">{count}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="heritage-toolbar-right">
          <span className="heritage-graph-stats muted">
            {t("graphNodesCount", { n: data.nodes.length })} • {t("graphEdgesCount", { n: data.edges.length })}
          </span>
          <div className="heritage-zoom-controls">
            <button
              type="button"
              className="btn secondary small heritage-btn"
              onClick={() => handleZoom(1.2)}
              title={t("zoomIn")}
              aria-label={t("zoomIn")}
            >
              +
            </button>
            <button
              type="button"
              className="btn secondary small heritage-btn"
              onClick={() => handleZoom(0.8)}
              title={t("zoomOut")}
              aria-label={t("zoomOut")}
            >
              −
            </button>
            <button
              type="button"
              className="btn secondary small heritage-btn"
              onClick={handleResetView}
              title={t("zoomReset")}
              aria-label={t("zoomReset")}
            >
              ⛶
            </button>
          </div>
        </div>
      </div>

      {/* Clean SVG Canvas */}
      <div
        className={`heritage-canvas-wrap ${isPanning ? "panning" : ""}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onWheel={handleWheel}
      >
        <svg
          ref={svgRef}
          className="heritage-svg"
          width={dimensions.width}
          height={dimensions.height}
          viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
        >
          {/* Pan & Zoom Group */}
          <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`}>
            {/* Edges */}
            <g className="heritage-edges">
              {data.edges.map((edge) => {
                const source = nodeMap.get(edge.from);
                const target = nodeMap.get(edge.to);
                if (!source || !target) return null;

                const isConnectedToFocus = activeFocusId !== null && (edge.from === activeFocusId || edge.to === activeFocusId);
                const isDimmed =
                  (activeFocusId !== null && !isConnectedToFocus) ||
                  (activeTypeFilter && source.type !== activeTypeFilter && target.type !== activeTypeFilter) ||
                  (matchingNodeIds && !matchingNodeIds.has(edge.from) && !matchingNodeIds.has(edge.to));

                const midX = (source.x + target.x) / 2;
                const midY = (source.y + target.y) / 2;

                return (
                  <g key={edge.id} className={`heritage-edge-group ${isConnectedToFocus ? "edge-active" : ""} ${isDimmed ? "edge-dimmed" : ""}`}>
                    <line
                      x1={source.x}
                      y1={source.y}
                      x2={target.x}
                      y2={target.y}
                      className="heritage-edge-line"
                    />
                    {isConnectedToFocus && (
                      <g transform={`translate(${midX}, ${midY})`} className="heritage-edge-label">
                        <rect x="-38" y="-11" width="76" height="22" rx="4" />
                        <text y="4">{edge.relation.replace(/_/g, " ")}</text>
                      </g>
                    )}
                  </g>
                );
              })}
            </g>

            {/* Nodes */}
            <g className="heritage-nodes">
              {nodes.map((node) => {
                const isSelected = selectedId === node.id;
                const isHovered = hoveredId === node.id;
                const isFocused = isSelected || isHovered;
                const isConnected = connectedNodeIds.has(node.id);
                const theme = TYPE_THEME[node.type] || DEFAULT_THEME;

                const matchesSearch = matchingNodeIds ? matchingNodeIds.has(node.id) : true;
                const matchesType = activeTypeFilter ? node.type === activeTypeFilter : true;

                const isDimmed =
                  (activeFocusId !== null && !isConnected) ||
                  !matchesSearch ||
                  !matchesType;

                const labelText = pickText(node.labels, lang);

                return (
                  <g
                    key={node.id}
                    data-node-id={node.id}
                    transform={`translate(${node.x}, ${node.y})`}
                    className={`heritage-node-group ${isSelected ? "selected" : ""} ${isHovered ? "hovered" : ""} ${isDimmed ? "dimmed" : ""}`}
                    onMouseEnter={() => setHoveredId(node.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (!dragRef.current.moved) {
                        onSelectNode(isSelected ? null : node.id);
                        triggerSimulation(0.3);
                      }
                    }}
                    cursor="pointer"
                  >
                    {/* 48px Touch Hit Target */}
                    <circle r={24} fill="transparent" />

                    {/* Outer Focus Ring */}
                    {isFocused && (
                      <circle
                        r={node.radius + 6}
                        fill="none"
                        stroke={isSelected ? "var(--brass)" : theme.color}
                        strokeWidth="3"
                        strokeDasharray={isSelected ? undefined : "3 3"}
                      />
                    )}

                    {/* Node Body */}
                    <circle
                      r={node.radius}
                      fill={isSelected ? theme.color : theme.bg}
                      stroke={theme.color}
                      strokeWidth="2.5"
                    />

                    {/* Inner icon or dot */}
                    <circle
                      r={node.radius > 12 ? 4 : 3}
                      fill={isSelected ? "#ffffff" : theme.color}
                    />

                    {/* Clean Label */}
                    <g className="heritage-node-label" transform={`translate(${node.radius + 8}, 4)`}>
                      <text
                        fill="var(--ink)"
                        fontWeight={isFocused ? "700" : "500"}
                        fontSize={node.type === "person" ? "14" : "12.5"}
                      >
                        {labelText}
                      </text>
                    </g>
                  </g>
                );
              })}
            </g>
          </g>
        </svg>

        <div className="heritage-graph-hint" aria-hidden="true">
          <span>{t("graphHint")}</span>
        </div>
      </div>
    </div>
  );
}
