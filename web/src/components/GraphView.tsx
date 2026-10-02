import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "../state";
import { pickText } from "./Bits";
import { STRINGS, type Key } from "../i18n";

export interface GraphNode {
  id: number;
  type: string;
  labels: Record<string, string>;
  description: string | null;
  item_ids: number[];
  items?: { id: number; title: string }[];
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

export const TYPE_ORDER = ["person", "organisation", "place", "event", "concept", "document"];

export function compareTypes(a: string, b: string): number {
  const ia = TYPE_ORDER.indexOf(a);
  const ib = TYPE_ORDER.indexOf(b);
  return (ia < 0 ? TYPE_ORDER.length : ia) - (ib < 0 ? TYPE_ORDER.length : ib) || a.localeCompare(b);
}

type TFn = (key: Key, vars?: Record<string, string | number>) => string;

function humanise(raw: string): string {
  const s = raw.replace(/[_-]+/g, " ").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

/** Visitor-facing name of a node type; unknown types fall back to readable text, never the raw i18n key. */
export function nodeTypeLabel(t: TFn, type: string): string {
  if (!type) return t("node_other" as Key);
  const key = `node_${type}`;
  return key in STRINGS.en ? t(key as Key) : humanise(type);
}

/** Visitor-facing name of a relation; unknown relations are humanised (spoke_at -> "spoke at"). */
export function relationLabel(t: TFn, relation: string): string {
  const key = `rel_${relation}`;
  return key in STRINGS.en ? t(key as Key) : relation.replace(/_/g, " ");
}

export function truncateLabel(text: string, max: number): string {
  const chars = Array.from(text);
  return chars.length > max ? `${chars.slice(0, max - 1).join("").trimEnd()}…` : text;
}

const NODE_LABEL_MAX = 24;
const EDGE_LABEL_MAX = 26;
const MIN_ZOOM = 0.2;
const MAX_ZOOM = 2.5;
const TAP_SLOP = 5;
const FALLBACK_SIZE = { width: 800, height: 520 };

export interface GraphViewProps {
  data: GraphData;
  selectedId: number | null;
  onSelectNode: (id: number | null) => void;
}

export function GraphView({ data, selectedId, onSelectNode }: GraphViewProps) {
  const { lang, t } = useSession();
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const [search, setSearch] = useState("");
  const [activeTypeFilter, setActiveTypeFilter] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [isPanning, setIsPanning] = useState(false);

  // The wrapper is the single source of truth for the canvas size; the SVG viewBox is its real pixel size.
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const sizeRef = useRef(size);
  sizeRef.current = size;
  const [transform, setTransform] = useState({ k: 1, x: 0, y: 0 });

  const simNodesRef = useRef<SimNode[]>([]);
  const simEdgesRef = useRef<GraphEdge[]>([]);
  const [renderCounter, setRenderCounter] = useState(0);

  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;
  const onSelectRef = useRef(onSelectNode);
  onSelectRef.current = onSelectNode;

  const needFitRef = useRef(false);

  const dragRef = useRef<{
    nodeId: number | null;
    isPanning: boolean;
    originX: number;
    originY: number;
    lastX: number;
    lastY: number;
    startTransformX: number;
    startTransformY: number;
    moved: boolean;
  }>({ nodeId: null, isPanning: false, originX: 0, originY: 0, lastX: 0, lastY: 0, startTransformX: 0, startTransformY: 0, moved: false });

  const degrees = useMemo(() => {
    const degMap = new Map<number, number>();
    for (const n of data.nodes) degMap.set(n.id, 0);
    for (const e of data.edges) {
      degMap.set(e.from, (degMap.get(e.from) ?? 0) + 1);
      degMap.set(e.to, (degMap.get(e.to) ?? 0) + 1);
    }
    return degMap;
  }, [data]);

  // Measure the wrapper (ResizeObserver) and keep viewBox == real pixel size.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      const width = Math.round(rect.width) || FALLBACK_SIZE.width;
      const height = Math.round(rect.height) || FALLBACK_SIZE.height;
      setSize((prev) => (prev && prev.width === width && prev.height === height ? prev : { width, height }));
    };
    measure();
    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(measure);
      ro.observe(el);
      return () => ro.disconnect();
    }
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  /** Zoom and pan so every node (plus room for its label) sits inside the canvas. */
  const fitView = useCallback(() => {
    const sz = sizeRef.current;
    const nodes = simNodesRef.current;
    if (!sz || !nodes.length) return;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of nodes) {
      const labelW = Math.min(Array.from(pickText(n.labels, "en")).length, NODE_LABEL_MAX) * 7 + 16;
      minX = Math.min(minX, n.x - n.radius - 8);
      maxX = Math.max(maxX, n.x + n.radius + 8 + labelW);
      minY = Math.min(minY, n.y - n.radius - 8);
      maxY = Math.max(maxY, n.y + n.radius + 8);
    }
    const pad = 28;
    const bw = Math.max(maxX - minX, 1);
    const bh = Math.max(maxY - minY, 1);
    const k = Math.max(MIN_ZOOM, Math.min((sz.width - pad * 2) / bw, (sz.height - pad * 2) / bh, 1.4));
    setTransform({
      k,
      x: sz.width / 2 - ((minX + maxX) / 2) * k,
      y: sz.height / 2 - ((minY + maxY) / 2) * k,
    });
  }, []);

  // Initial layout: a ring that fits the canvas; nodes already placed keep their position.
  const hasSize = size !== null;
  useEffect(() => {
    const sz = sizeRef.current;
    if (!sz || !data.nodes.length) {
      simNodesRef.current = [];
      return;
    }
    const cx = sz.width / 2;
    const cy = sz.height / 2;
    const ring = Math.min(sz.width, sz.height) * 0.35;
    const ordered = [...data.nodes].sort((a, b) => compareTypes(a.type, b.type));
    const initialNodes: SimNode[] = ordered.map((node, i) => {
      const existing = simNodesRef.current.find((n) => n.id === node.id);
      const deg = degrees.get(node.id) ?? 0;
      const radius = node.type === "person" ? 15 : 12 + Math.min(deg, 4);
      if (existing) return { ...existing, ...node, radius, degree: deg };
      const a = (i / ordered.length) * Math.PI * 2 - Math.PI / 2;
      const r = ordered.length === 1 ? 0 : ring;
      return { ...node, x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r, vx: 0, vy: 0, radius, degree: deg };
    });
    simNodesRef.current = initialNodes;
    simEdgesRef.current = data.edges;
    needFitRef.current = true;
    alphaRef.current = Math.max(alphaRef.current, 0.3);
    fitView();
    setRenderCounter((c) => c + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, degrees, hasSize, fitView]);

  // On a real resize, re-fit what is already laid out.
  useEffect(() => {
    if (size && simNodesRef.current.length) fitView();
  }, [size, fitView]);

  const animFrameRef = useRef<number | null>(null);
  const alphaRef = useRef(0.3);

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
      const sz = sizeRef.current;

      if (sz && nodes.length > 0 && alpha > 0.002) {
        const cx = sz.width / 2;
        const cy = sz.height / 2;
        // Spacing scales with the canvas and the node count, so a 6-node map is compact and a 60-node map spreads out.
        const spacing = Math.max(70, Math.min(200, Math.sqrt((sz.width * sz.height) / nodes.length) * 0.6));
        const repel = spacing * spacing * 1.2;
        const soft = spacing * spacing * 0.03;

        for (const n of nodes) {
          if (n.pinned) continue;
          n.vx += (cx - n.x) * 0.9 * alpha * dt;
          n.vy += (cy - n.y) * 0.9 * alpha * dt;
        }

        for (let i = 0; i < nodes.length; i++) {
          const n1 = nodes[i];
          for (let j = i + 1; j < nodes.length; j++) {
            const n2 = nodes[j];
            const dx = n2.x - n1.x;
            const dy = n2.y - n1.y;
            const distSq = dx * dx + dy * dy + soft;
            const dist = Math.sqrt(distSq);
            const force = (repel * alpha * dt) / distSq;
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

            const minSeparation = n1.radius + n2.radius + spacing * 0.3;
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

        const nodeById = new Map(nodes.map((n) => [n.id, n]));
        for (const e of edges) {
          const s = nodeById.get(e.from);
          const tr = nodeById.get(e.to);
          if (!s || !tr) continue;
          const dx = tr.x - s.x;
          const dy = tr.y - s.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = (dist - spacing) * 1.8 * alpha * dt;
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

        for (const n of nodes) {
          if (n.pinned) continue;
          n.vx *= 0.88;
          n.vy *= 0.88;
          n.x += n.vx * dt * 60;
          n.y += n.vy * dt * 60;
        }

        alphaRef.current *= 0.985;
        if (alphaRef.current <= 0.002 && needFitRef.current) {
          needFitRef.current = false;
          fitView();
        }
        setRenderCounter((c) => (c + 1) % 1000000);
      }

      animFrameRef.current = requestAnimationFrame(tick);
    };

    animFrameRef.current = requestAnimationFrame(tick);
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [fitView]);

  // Hover focus only applies to a real mouse; on touch it would stick after a tap.
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

  /** Wrapper pixels per SVG unit's inverse: how many viewBox units one client pixel is worth. */
  const pointerScale = () => {
    const rect = wrapRef.current?.getBoundingClientRect();
    const sz = sizeRef.current;
    return rect && rect.width > 0 && sz ? sz.width / rect.width : 1;
  };

  const zoomAround = useCallback((factor: number, px: number, py: number) => {
    needFitRef.current = false;
    setTransform((prev) => {
      const newK = Math.max(MIN_ZOOM, Math.min(prev.k * factor, MAX_ZOOM));
      const f = newK / prev.k;
      return { k: newK, x: px - (px - prev.x) * f, y: py - (py - prev.y) * f };
    });
  }, []);

  const handleZoom = (delta: number) => {
    const sz = sizeRef.current ?? FALLBACK_SIZE;
    zoomAround(delta, sz.width / 2, sz.height / 2);
  };

  const handleResetView = () => {
    fitView();
    needFitRef.current = true;
    triggerSimulation(0.3);
  };

  // Native, non-passive wheel listener so preventDefault actually stops the page scrolling.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const sz = sizeRef.current;
      const scale = rect.width > 0 && sz ? sz.width / rect.width : 1;
      zoomAround(e.deltaY < 0 ? 1.08 : 0.92, (e.clientX - rect.left) * scale, (e.clientY - rect.top) * scale);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAround]);

  const handlePointerDown = (e: React.PointerEvent) => {
    const target = e.target as HTMLElement | SVGElement;
    const nodeG = target.closest<SVGGElement>("[data-node-id]");

    try {
      (e.currentTarget as Element).setPointerCapture(e.pointerId);
    } catch {
      // Pointer capture unsupported
    }

    const base = {
      originX: e.clientX,
      originY: e.clientY,
      lastX: e.clientX,
      lastY: e.clientY,
      startTransformX: transform.x,
      startTransformY: transform.y,
      moved: false,
    };

    if (nodeG) {
      const nodeId = Number(nodeG.getAttribute("data-node-id"));
      const node = simNodesRef.current.find((n) => n.id === nodeId);
      if (node) {
        node.pinned = true;
        dragRef.current = { ...base, nodeId, isPanning: false };
      }
    } else {
      setIsPanning(true);
      dragRef.current = { ...base, nodeId: null, isPanning: true };
    }
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (d.nodeId === null && !d.isPanning) return;
    if (!d.moved && Math.hypot(e.clientX - d.originX, e.clientY - d.originY) > TAP_SLOP) {
      d.moved = true;
      needFitRef.current = false;
    }
    if (!d.moved) return;
    const scale = pointerScale();

    if (d.nodeId !== null) {
      const node = simNodesRef.current.find((n) => n.id === d.nodeId);
      if (node) {
        node.x += ((e.clientX - d.lastX) * scale) / transform.k;
        node.y += ((e.clientY - d.lastY) * scale) / transform.k;
        node.vx = 0;
        node.vy = 0;
        triggerSimulation(0.3);
        setRenderCounter((c) => (c + 1) % 1000000);
      }
      d.lastX = e.clientX;
      d.lastY = e.clientY;
    } else if (d.isPanning) {
      setTransform((prev) => ({
        ...prev,
        x: d.startTransformX + (e.clientX - d.originX) * scale,
        y: d.startTransformY + (e.clientY - d.originY) * scale,
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
    const cancelled = e.type === "pointercancel";

    if (nodeId !== null) {
      const node = simNodesRef.current.find((n) => n.id === nodeId);
      if (node) node.pinned = false;
      // The only place a tap selects: a press that stayed put.
      if (!moved && !cancelled) toggleSelect(nodeId);
      triggerSimulation(0.2);
    } else if (!moved && !cancelled && dragRef.current.isPanning) {
      onSelectRef.current(null);
    }

    dragRef.current = { ...dragRef.current, nodeId: null, isPanning: false, moved: false };
    setIsPanning(false);
  };

  const toggleSelect = (id: number) => {
    onSelectRef.current(selectedIdRef.current === id ? null : id);
  };

  const matchingNodeIds = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return null;
    const matches = new Set<number>();
    for (const n of data.nodes) {
      const label = pickText(n.labels, lang).toLowerCase();
      const desc = (n.description ?? "").toLowerCase();
      if (label.includes(q) || desc.includes(q)) matches.add(n.id);
    }
    return matches;
  }, [search, data.nodes, lang]);

  const nodes = simNodesRef.current;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes, renderCounter]);

  const availableTypes = useMemo(() => {
    const s = new Set<string>();
    for (const n of data.nodes) s.add(n.type);
    return Array.from(s).sort(compareTypes);
  }, [data.nodes]);

  const vw = size?.width ?? FALLBACK_SIZE.width;
  const vh = size?.height ?? FALLBACK_SIZE.height;

  return (
    <div className="heritage-graph-container">
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
                  <span>{nodeTypeLabel(t, type)}</span>
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
            <button type="button" className="btn secondary small heritage-btn" onClick={() => handleZoom(1.2)} title={t("zoomIn")} aria-label={t("zoomIn")}>
              +
            </button>
            <button type="button" className="btn secondary small heritage-btn" onClick={() => handleZoom(0.8)} title={t("zoomOut")} aria-label={t("zoomOut")}>
              −
            </button>
            <button type="button" className="btn secondary small heritage-btn" onClick={handleResetView} title={t("zoomReset")} aria-label={t("zoomReset")}>
              ⛶
            </button>
          </div>
        </div>
      </div>

      <div
        ref={wrapRef}
        className={`heritage-canvas-wrap ${isPanning ? "panning" : ""}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
      >
        <svg
          ref={svgRef}
          className="heritage-svg"
          viewBox={`0 0 ${vw} ${vh}`}
          role="group"
          aria-label={t("mapGraphDesc")}
        >
          <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`}>
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

                return (
                  <g key={edge.id} className={`heritage-edge-group ${isConnectedToFocus ? "edge-active" : ""} ${isDimmed ? "edge-dimmed" : ""}`}>
                    <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} className="heritage-edge-line" />
                  </g>
                );
              })}
            </g>

            <g className="heritage-nodes">
              {nodes.map((node) => {
                const isSelected = selectedId === node.id;
                const isHovered = hoveredId === node.id;
                const isFocused = isSelected || isHovered;
                const isConnected = connectedNodeIds.has(node.id);
                const theme = TYPE_THEME[node.type] || DEFAULT_THEME;

                const matchesSearch = matchingNodeIds ? matchingNodeIds.has(node.id) : true;
                const matchesType = activeTypeFilter ? node.type === activeTypeFilter : true;
                const isDimmed = (activeFocusId !== null && !isConnected) || !matchesSearch || !matchesType;

                const labelFull = pickText(node.labels, lang);
                const labelText = truncateLabel(labelFull, NODE_LABEL_MAX);
                const typeText = nodeTypeLabel(t, node.type);

                return (
                  <g
                    key={node.id}
                    data-node-id={node.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`${labelFull}, ${typeText}`}
                    aria-pressed={isSelected}
                    transform={`translate(${node.x}, ${node.y})`}
                    className={`heritage-node-group ${isSelected ? "selected" : ""} ${isHovered ? "hovered" : ""} ${isDimmed ? "dimmed" : ""}`}
                    onPointerEnter={(e) => {
                      if (e.pointerType === "mouse") setHoveredId(node.id);
                    }}
                    onPointerLeave={(e) => {
                      if (e.pointerType === "mouse") setHoveredId(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        toggleSelect(node.id);
                        triggerSimulation(0.2);
                      }
                    }}
                    cursor="pointer"
                  >
                    <circle r={24} fill="transparent" />

                    <circle className="heritage-focus-ring" r={node.radius + 9} fill="none" strokeWidth="3" />

                    {isFocused && (
                      <circle
                        r={node.radius + 6}
                        fill="none"
                        stroke={isSelected ? "var(--brass)" : theme.color}
                        strokeWidth="3"
                        strokeDasharray={isSelected ? undefined : "3 3"}
                      />
                    )}

                    <circle r={node.radius} fill={isSelected ? theme.color : theme.bg} stroke={theme.color} strokeWidth="2.5" />
                    <circle r={node.radius > 12 ? 4 : 3} fill={isSelected ? "#ffffff" : theme.color} />

                    <g className="heritage-node-label" transform={`translate(${node.radius + 8}, 4)`}>
                      <text fill="var(--ink)" fontWeight={isFocused ? "700" : "500"} fontSize={node.type === "person" ? "14" : "12.5"}>
                        {labelText !== labelFull && <title>{labelFull}</title>}
                        {labelText}
                      </text>
                    </g>
                  </g>
                );
              })}
            </g>

            {/* Edge labels sit above the nodes (and their faded labels) on an opaque plate, only for the focused node's edges. */}
            <g className="heritage-edge-labels">
              {data.edges.map((edge) => {
                if (activeFocusId === null || (edge.from !== activeFocusId && edge.to !== activeFocusId)) return null;
                const source = nodeMap.get(edge.from);
                const target = nodeMap.get(edge.to);
                if (!source || !target) return null;
                const midX = (source.x + target.x) / 2;
                const midY = (source.y + target.y) / 2;
                const relFull = relationLabel(t, edge.relation);
                const relShown = truncateLabel(relFull, EDGE_LABEL_MAX);
                const labelW = Math.max(36, Array.from(relShown).length * 6.8 + 18);
                return (
                  <g key={edge.id} transform={`translate(${midX}, ${midY})`} className="heritage-edge-label">
                    <title>{relFull}</title>
                    <rect x={-labelW / 2} y="-11" width={labelW} height="22" rx="4" />
                    <text y="1">{relShown}</text>
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
