import { useCallback, useEffect, useState } from 'react'

import { BasicsStep } from '../components/therapist/BasicsStep'
import { DemoStep } from '../components/therapist/DemoStep'
import { ParametersEditor } from '../components/therapist/ParametersEditor'
import { ReviewStep } from '../components/therapist/ReviewStep'
import { usePoseStream } from '../hooks/usePoseStream'
import { getTopology } from '../services/api'
import { JOINT_LABEL, draftFromAnalysis, type Basics } from '../services/authoring'
import {
  analyzeDemonstration,
  approveCustomExercise,
  archiveCustomExercise,
  createCustomExercise,
  listCustomExercises,
  updateCustomExercise,
} from '../services/authoringApi'
import type { AnalysisResult, AnalyzeRequest, CustomExercise, DemonstrationInfo, DraftFields, SuggestedRule } from '../types/authoring'
import type { Topology } from '../types/protocol'
import '../therapist.css'

type Step = 'list' | 'basics' | 'demo' | 'review' | 'edit'

const EMPTY_BASICS: Basics = { name: '', description: '', instructionsText: '', cameraView: 'side', cameraGuidance: '' }

/**
 * Therapist workspace: create custom exercises from a demonstration, review
 * the suggested parameters, edit, and approve. Nothing reaches patients until
 * approved. No login yet — local use only (see docs/CUSTOM_EXERCISES.md).
 */
export function TherapistPage() {
  const stream = usePoseStream()
  const [step, setStep] = useState<Step>('list')
  const [items, setItems] = useState<CustomExercise[]>([])
  const [topology, setTopology] = useState<Topology | null>(null)
  const [basics, setBasics] = useState<Basics>(EMPTY_BASICS)
  const [demo, setDemo] = useState<DemonstrationInfo | null>(null)
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null)
  const [rules, setRules] = useState<SuggestedRule[]>([])
  const [fields, setFields] = useState<DraftFields | null>(null)
  const [record, setRecord] = useState<CustomExercise | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = useCallback(() => {
    listCustomExercises()
      .then(setItems)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  useEffect(() => {
    if (stream.connection !== 'open') return
    refresh()
    getTopology()
      .then(setTopology)
      .catch((err: unknown) => setError(String(err)))
  }, [stream.connection, refresh])

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const startNew = () => {
    setBasics(EMPTY_BASICS)
    setDemo(null)
    setAnalysis(null)
    setFields(null)
    setRecord(null)
    setNotice(null)
    setStep('basics')
  }

  const onRecorded = (d: DemonstrationInfo) =>
    void run(async () => {
      setDemo(d)
      const a = await analyzeDemonstration(d.demo_id)
      setAnalysis(a)
      setRules(a.suggested_rules)
      setStep('review')
    })

  const reanalyze = (req: AnalyzeRequest) =>
    demo &&
    void run(async () => {
      const a = await analyzeDemonstration(demo.demo_id, req)
      setAnalysis(a)
      setRules(a.suggested_rules)
    })

  const toEdit = () => {
    if (!analysis) return
    const draft = draftFromAnalysis(basics, analysis, rules)
    if (!draft) return
    setFields(draft)
    setStep('edit')
  }

  const save = (storeAngleData: boolean) =>
    fields &&
    void run(async () => {
      const rec = record
        ? await updateCustomExercise(record.id, fields)
        : await createCustomExercise(fields, demo?.demo_id ?? null, storeAngleData)
      setRecord(rec)
      setFields(rec.fields)
      setNotice(`Saved as a draft (version ${rec.version}). Approve it to offer it to patients.`)
      refresh()
    })

  const approve = (reviewer: string, attestation: boolean) =>
    record &&
    void run(async () => {
      const rec = await approveCustomExercise(record.id, reviewer, attestation)
      setRecord(rec)
      setNotice(`Approved by ${rec.approved_by}. “${rec.fields.name}” is now available on the mirror.`)
      refresh()
    })

  const archive = () =>
    record &&
    void run(async () => {
      const rec = await archiveCustomExercise(record.id)
      setRecord(rec)
      setNotice('Archived. It is no longer offered to patients.')
      refresh()
    })

  const open = (rec: CustomExercise) => {
    setRecord(rec)
    setFields(rec.fields)
    setAnalysis(null)
    setDemo(null)
    setNotice(null)
    setStep('edit')
  }

  return (
    <div className="therapist">
      <header className="app-header">
        <div className="brand">
          <span className="brand-name">PT Smart Mirror</span>
          <span className="brand-sub">
            Therapist workspace · custom exercises · <a href="#/dev">Developer console</a> · <a href="#/">Mirror view</a>
          </span>
        </div>
      </header>
      <p className="t-banner">
        Local prototype without sign-in: use only on this computer. Parameters suggested from a demonstration are camera
        estimates and must be reviewed by the treating therapist before approval.
      </p>
      {notice && (
        <p className="t-notice" role="status">
          {notice}
        </p>
      )}
      {error && step !== 'edit' && step !== 'demo' && (
        <p className="form-error t-page-error" role="alert">
          {error}
        </p>
      )}
      <main className="t-main">
        {step === 'list' && <ExerciseList items={items} onNew={startNew} onOpen={open} />}
        {step === 'basics' && <BasicsStep basics={basics} onChange={setBasics} onNext={() => setStep('demo')} onCancel={() => setStep('list')} />}
        {step === 'demo' && (
          <>
            <DemoStep stream={stream} topology={topology} onRecorded={onRecorded} onBack={() => setStep('basics')} />
            {busy && <p className="hint">Analysing the demonstration…</p>}
            {error && <p className="form-error">{error}</p>}
          </>
        )}
        {step === 'review' && demo && analysis && (
          <ReviewStep
            demo={demo}
            analysis={analysis}
            busy={busy}
            rules={rules}
            onRules={setRules}
            onReanalyze={reanalyze}
            onNext={toEdit}
            onRedo={() => setStep('demo')}
          />
        )}
        {step === 'edit' && fields && (
          <ParametersEditor
            fields={fields}
            onChange={setFields}
            analysis={analysis}
            record={record}
            hasDemo={demo !== null}
            busy={busy}
            error={error}
            onSave={save}
            onApprove={approve}
            onArchive={archive}
            onClose={() => {
              setStep('list')
              setNotice(null)
              setError(null)
            }}
          />
        )}
      </main>
    </div>
  )
}

function ExerciseList({ items, onNew, onOpen }: { items: CustomExercise[]; onNew: () => void; onOpen: (r: CustomExercise) => void }) {
  return (
    <section className="t-step">
      <div className="t-list-head">
        <h2>Custom exercises</h2>
        <button className="btn btn-primary" onClick={onNew}>
          New exercise from a demonstration
        </button>
      </div>
      {items.length === 0 ? (
        <p className="hint">None yet. Create one by demonstrating the movement to the camera or uploading a video.</p>
      ) : (
        <table className="t-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Counts on</th>
              <th>Start → target</th>
              <th>Updated</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id}>
                <td>{r.fields.name}</td>
                <td>
                  <span className={`t-pill t-status-${r.status}`}>{r.status}</span> v{r.version}
                  {r.status === 'draft' && r.live_version ? ` (v${r.live_version} live)` : ''}
                </td>
                <td>
                  {JOINT_LABEL[r.fields.signal_joint] ?? r.fields.signal_joint} ·{' '}
                  {r.fields.side_mode === 'single' ? (r.fields.default_side ?? '') : 'both sides'}
                </td>
                <td>
                  {r.fields.rep_counting.start_deg}° → {r.fields.rep_counting.target_deg}°
                </td>
                <td>{new Date(r.updated_at).toLocaleString()}</td>
                <td>
                  <button className="btn btn-ghost" onClick={() => onOpen(r)}>
                    Open
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
