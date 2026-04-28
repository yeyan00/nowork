import { useEffect, useRef, useCallback } from 'react';
import * as d3 from 'd3';
import type { WikiGraphData } from '../lib/backend';

interface Props {
  data: WikiGraphData;
  onPageClick: (path: string) => void;
}

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  title: string;
  type: string;
  path: string;
  group: string;
}

interface SimEdge extends d3.SimulationLinkDatum<SimNode> {
  source_path: string;
}

export function WikiGraphView({ data, onPageClick }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simRef = useRef<d3.Simulation<SimNode, SimEdge> | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  const cleanup = useCallback(() => {
    if (simRef.current) {
      simRef.current.stop();
      simRef.current = null;
    }
    if (tooltipRef.current) {
      tooltipRef.current.remove();
      tooltipRef.current = null;
    }
  }, []);

  const render = useCallback(() => {
    if (!svgRef.current || !containerRef.current || data.nodes.length === 0) return;

    cleanup();

    const container = containerRef.current;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const rect = container.getBoundingClientRect();
    const width = Math.max(rect.width, 400);
    const height = Math.max(rect.height, 400);

    svg.attr('viewBox', `0 0 ${width} ${height}`)
      .style('width', '100%')
      .style('height', '100%');

    const nodes: SimNode[] = data.nodes.map((n) => ({ ...n }));
    const edges: SimEdge[] = data.edges.map((e) => ({
      source: e.source,
      target: e.target,
      source_path: e.source_path,
    }));

    const orphanSet = new Set(data.stats.orphan_nodes);

    const simulation = d3
      .forceSimulation<SimNode>(nodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, SimEdge>(edges)
          .id((d) => d.id)
          .distance(60),
      )
      .force('charge', d3.forceManyBody().strength(-120))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(18));

    simRef.current = simulation;

    const g = svg.append('g');

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    g.append('defs')
      .append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 18)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#b0bec5');

    const link = g
      .append('g')
      .selectAll('line')
      .data(edges)
      .join('line')
      .attr('stroke', '#c8d4e0')
      .attr('stroke-width', 1)
      .attr('marker-end', 'url(#arrowhead)');

    const node = g
      .append('g')
      .selectAll<SVGGElement, SimNode>('g')
      .data(nodes)
      .join('g')
      .style('cursor', (d) => (d.path ? 'pointer' : 'default'));

    node
      .append('circle')
      .attr('r', (d) => (orphanSet.has(d.id) ? 6 : 8))
      .attr('fill', (d) => d.group)
      .attr('stroke', (d) => (orphanSet.has(d.id) ? '#e53935' : '#fff'))
      .attr('stroke-width', (d) => (orphanSet.has(d.id) ? 2 : 1.5))
      .attr('opacity', 0.9);

    node
      .append('text')
      .text((d) => d.title.length > 16 ? d.title.slice(0, 15) + '...' : d.title)
      .attr('dy', -12)
      .attr('text-anchor', 'middle')
      .attr('font-size', '10px')
      .attr('fill', '#475569')
      .attr('pointer-events', 'none');

    const tooltip = document.createElement('div');
    tooltip.className = 'wiki-graph-tooltip';
    container.appendChild(tooltip);
    tooltipRef.current = tooltip;

    node
      .on('mouseenter', (event, d) => {
        tooltip.innerHTML = `<strong>${d.title}</strong><br/>type: ${d.type}${d.path ? '<br/>path: ' + d.path : ''}`;
        tooltip.style.left = event.offsetX + 12 + 'px';
        tooltip.style.top = event.offsetY - 8 + 'px';
        tooltip.style.opacity = '1';
      })
      .on('mouseleave', () => {
        tooltip.style.opacity = '0';
      })
      .on('click', (_event, d) => {
        if (d.path) {
          onPageClick(d.path);
        }
      });

    const drag = d3
      .drag<SVGGElement, SimNode>()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    node.call(drag as unknown as (selection: d3.Selection<SVGGElement, SimNode, SVGGElement, unknown>) => void);

    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as SimNode).x ?? 0)
        .attr('y1', (d) => (d.source as SimNode).y ?? 0)
        .attr('x2', (d) => (d.target as SimNode).x ?? 0)
        .attr('y2', (d) => (d.target as SimNode).y ?? 0);

      node.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });
  }, [data, onPageClick, cleanup]);

  useEffect(() => {
    requestAnimationFrame(() => {
      render();
    });
    return cleanup;
  }, [render, cleanup]);

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(() => {
      render();
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [render]);

  const legendItems = [
    { type: 'entity', color: '#4c78ff' },
    { type: 'concept', color: '#22c55e' },
    { type: 'source', color: '#f59e0b' },
    { type: 'query', color: '#a855f7' },
    { type: 'missing', color: '#e53935' },
  ].filter((item) => data.stats.by_type[item.type]);

  return (
    <div className="wiki-graph-view">
      {legendItems.length > 0 && (
        <div className="wiki-graph-legend">
          {legendItems.map((item) => (
            <span key={item.type} className="wiki-graph-legend-item">
              <span className="wiki-graph-legend-dot" style={{ background: item.color }} />
              {item.type} ({data.stats.by_type[item.type]})
            </span>
          ))}
          {data.stats.orphan_nodes.length > 0 && (
            <span className="wiki-graph-legend-item" style={{ color: '#e53935' }}>
              orphans: {data.stats.orphan_nodes.length}
            </span>
          )}
        </div>
      )}
      <div ref={containerRef} className="wiki-graph-canvas">
        <svg ref={svgRef} />
      </div>
    </div>
  );
}
