import type { ManagementCard } from '../types';

interface ManagementPageProps {
  title: string;
  subtitle: string;
  cards: ManagementCard[];
}

export function ManagementPage({ title, subtitle, cards }: ManagementPageProps) {
  return (
    <section className="page-frame">
      <header className="page-header">
        <div>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        <button type="button" className="primary-button">
          Add
        </button>
      </header>

      <div className="card-grid">
        {cards.map((card) => (
          <article key={card.title} className="info-card">
            <strong>{card.title}</strong>
            <p>{card.description}</p>
            <span>{card.meta}</span>
          </article>
        ))}
      </div>
    </section>
  );
}
