import type { ExerciseSummary } from '../../types/protocol'

interface Props {
  library: ExerciseSummary[]
  onChoose: (exerciseId: string) => void
}

/** Exercise picker. Start opens the settings screen (defaults or adjust). */
export function HomeScreen({ library, onChoose }: Props) {
  return (
    <section className="m-home" aria-labelledby="m-home-title">
      <h1 id="m-home-title" className="m-title">
        Choose an exercise
      </h1>
      {library.length === 0 ? (
        <p className="m-muted">Loading exercises…</p>
      ) : (
        <ul className="m-cards">
          {library.map((x) => (
            <li key={x.id} className="m-card">
              <div className="m-card-head">
                <h2>{x.name}</h2>
                {x.is_demo && <span className="m-badge">Demo values</span>}
              </div>
              <p className="m-muted">{x.description}</p>
              <p className="m-card-meta">
                {x.dosage.sets ?? 1} {(x.dosage.sets ?? 1) === 1 ? 'set' : 'sets'} × {x.dosage.reps_per_set ?? 10} reps ·
                Camera: {x.camera_view === 'side' ? 'side-on' : 'facing the screen'}
                {x.side_mode === 'single' ? ' · one side' : ''}
              </p>
              <button className="m-btn m-btn-primary" onClick={() => onChoose(x.id)}>
                Start
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
