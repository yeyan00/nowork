interface StaticCanvasProps {
  title: string;
  nodes: string[];
}

export function StaticCanvas({ title, nodes }: StaticCanvasProps) {
  return (
    <section className="canvas-card">
      <div className="canvas-header">
        <strong>{title}</strong>
        <span>Static orchestration preview</span>
      </div>
      <div className="canvas-nodes">
        {nodes.map((node, index) => (
          <div key={node} className="canvas-node">
            <span>{index + 1}</span>
            <strong>{node}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
