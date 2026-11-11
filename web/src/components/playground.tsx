import { useEffect, useState } from "react"
import { ArrowDown, ArrowUp, Plus, Trash2, Play, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { api, number, type Snapshot } from "@/lib/api"

type Step = {
  strategy: string
  args: Record<string, string | number | string[]>
}
type Parameter = {
  type: string
  choices?: string[]
  minimum?: number
  maximum?: number
}
type Catalog = {
  recipes: { id: string; name: string; description: string; steps: Step[] }[]
  parameters: Record<string, Record<string, Parameter>>
  errors: { file: string; error: string }[]
}
type Checkpoint = {
  candidate_id: string
  available: boolean
  reason: string | null
}

export function Playground({
  snapshot,
  selected,
  onQueued,
}: {
  snapshot: Snapshot
  selected: string
  onQueued: (id: string) => void
}) {
  const saved = snapshot.manifest.config as
    | {
        manual_plan?: Step[]
        python?: string
        max_runtime_minutes?: number
        advanced?: Record<string, unknown>
      }
    | undefined
  const [catalog, setCatalog] = useState<Catalog>()
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([])
  const [checkpoint, setCheckpoint] = useState("")
  const [recipe, setRecipe] = useState("")
  const [steps, setSteps] = useState<(Step & { key: string })[]>(() =>
    structuredClone(saved?.manual_plan || []).map((s) => ({
      ...s,
      key: crypto.randomUUID(),
    }))
  )
  const [runtime, setRuntime] = useState(saved?.max_runtime_minutes || 60)
  const [python, setPython] = useState(saved?.python || "")
  const [advanced, setAdvanced] = useState(
    JSON.stringify(saved?.advanced || {}, null, 2)
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [dragged, setDragged] = useState<number | null>(null)
  useEffect(() => {
    let current = true
    Promise.all([
      api<Catalog>("/recipes"),
      api<{ checkpoints: Checkpoint[] }>(`/runs/${snapshot.id}/checkpoints`),
    ])
      .then(([recipes, result]) => {
        if (current) {
          setCatalog(recipes)
          setCheckpoints(result.checkpoints)
        }
      })
      .catch((e: Error) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [snapshot.id, snapshot.sequence])
  const chosen =
    checkpoints.find((c) => c.candidate_id === (checkpoint || selected)) ||
    checkpoints.find((c) => c.available) ||
    checkpoints[0]
  const chosenRecipe =
    catalog?.recipes.find((r) => r.id === recipe) || catalog?.recipes[0]
  function move(from: number, to: number) {
    if (to < 0 || to >= steps.length) return
    setSteps((previous) => {
      const next = [...previous]
      const [step] = next.splice(from, 1)
      next.splice(to, 0, step)
      return next
    })
  }
  function edit(
    index: number,
    name: string,
    value: string | number | string[]
  ) {
    setSteps((previous) =>
      previous.map((s, i) =>
        i === index ? { ...s, args: { ...s.args, [name]: value } } : s
      )
    )
  }
  async function run() {
    setBusy(true)
    setError("")
    try {
      const result = await api<{ job_id: string }>(
        `/runs/${snapshot.id}/playground`,
        {
          candidate_id: chosen?.candidate_id,
          steps: steps.map(({ strategy, args }) => ({ strategy, args })),
          max_runtime_minutes: runtime,
          ...(python.trim() ? { python: python.trim() } : {}),
          advanced: JSON.parse(advanced),
        }
      )
      onQueued(result.job_id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="mx-auto max-w-3xl space-y-5 p-5">
      <div className="space-y-2">
        <Label htmlFor="playground-checkpoint">Checkpoint</Label>
        <select
          id="playground-checkpoint"
          className="h-9 w-full border bg-background px-2 text-xs"
          value={chosen?.candidate_id || ""}
          onChange={(e) => setCheckpoint(e.target.value)}
        >
          {!checkpoints.length && <option value="">No checkpoints</option>}
          {checkpoints.map((c) => {
            const node = snapshot.nodes.find(
              (n) => n.node_id === c.candidate_id
            )
            return (
              <option key={c.candidate_id} value={c.candidate_id}>
                {node?.strategy || "Baseline"} · {c.candidate_id} ·{" "}
                {number(node?.fmax_improvement_mhz, 2)} MHz
                {!c.available ? " · unavailable" : ""}
              </option>
            )
          })}
        </select>
        {chosen && !chosen.available && (
          <p className="text-xs text-muted-foreground">{chosen.reason}</p>
        )}
      </div>
      <div className="flex items-end gap-2">
        <div className="flex-1 space-y-2">
          <Label htmlFor="playground-recipe">Recipe</Label>
          <select
            id="playground-recipe"
            className="h-9 w-full border bg-background px-2 text-xs"
            value={chosenRecipe?.id || ""}
            onChange={(e) => setRecipe(e.target.value)}
          >
            {catalog?.recipes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
        <Button
          variant="outline"
          disabled={
            !chosenRecipe ||
            steps.length + (chosenRecipe?.steps.length || 0) > 32
          }
          onClick={() =>
            setSteps((previous) => [
              ...previous,
              ...structuredClone(chosenRecipe!.steps).map((s) => ({
                ...s,
                key: crypto.randomUUID(),
              })),
            ])
          }
        >
          <Plus /> Add recipe
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Reload recipes"
          title="Reload recipes"
          onClick={() =>
            void api<Catalog>("/recipes")
              .then(setCatalog)
              .catch((e: Error) => setError(e.message))
          }
        >
          <RefreshCw />
        </Button>
      </div>
      <ol className="space-y-2" aria-label="Recipe sequence">
        {steps.map((step, index) => (
          <li
            key={step.key}
            className="space-y-3 border p-3"
            draggable
            onDragStart={() => setDragged(index)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              if (dragged !== null) move(dragged, index)
              setDragged(null)
            }}
            onDragEnd={() => setDragged(null)}
          >
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">
                {index + 1}.
              </span>
              <span className="flex-1 text-xs font-medium">
                {catalog?.recipes.find(
                  (r) =>
                    r.steps.length === 1 &&
                    r.steps[0].strategy === step.strategy
                )?.name || step.strategy.replaceAll("_", " ")}
              </span>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Move step ${index + 1} up`}
                disabled={!index}
                onClick={() => move(index, index - 1)}
              >
                <ArrowUp />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Move step ${index + 1} down`}
                disabled={index === steps.length - 1}
                onClick={() => move(index, index + 1)}
              >
                <ArrowDown />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remove step ${index + 1}`}
                onClick={() =>
                  setSteps((previous) => previous.filter((_, i) => i !== index))
                }
              >
                <Trash2 />
              </Button>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(catalog?.parameters[step.strategy] || {}).map(
                ([name, spec]) => {
                  const id = `${step.key}-${name}`
                  return (
                    <div key={name} className="space-y-1">
                      <Label htmlFor={id}>{name.replaceAll("_", " ")}</Label>
                      {spec.type === "choice" ? (
                        <select
                          id={id}
                          className="h-8 w-full border bg-background px-2 text-xs"
                          value={String(step.args[name])}
                          onChange={(e) => edit(index, name, e.target.value)}
                        >
                          {spec.choices?.map((c) => (
                            <option key={c}>{c}</option>
                          ))}
                        </select>
                      ) : spec.type === "multi_choice" ? (
                        <select
                          id={id}
                          multiple
                          className="w-full border bg-background px-2 text-xs"
                          value={step.args[name] as string[]}
                          onChange={(e) =>
                            edit(
                              index,
                              name,
                              [...e.target.selectedOptions].map((o) => o.value)
                            )
                          }
                        >
                          {spec.choices?.map((c) => (
                            <option key={c}>{c}</option>
                          ))}
                        </select>
                      ) : (
                        <Input
                          id={id}
                          type="number"
                          min={spec.minimum}
                          max={spec.maximum}
                          step={spec.type === "integer" ? 1 : "any"}
                          value={
                            Number.isFinite(step.args[name])
                              ? Number(step.args[name])
                              : ""
                          }
                          onChange={(e) =>
                            edit(
                              index,
                              name,
                              e.target.value === ""
                                ? ""
                                : Number(e.target.value)
                            )
                          }
                        />
                      )}
                    </div>
                  )
                }
              )}
            </div>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="w-32 space-y-2">
          <Label htmlFor="playground-runtime">Time limit (min)</Label>
          <Input
            id="playground-runtime"
            type="number"
            min="1"
            value={runtime}
            onChange={(e) => setRuntime(Number(e.target.value))}
          />
        </div>
        <Button
          disabled={busy || !steps.length || !chosen?.available || runtime <= 0}
          onClick={() => void run()}
        >
          <Play /> {busy ? "Queuing…" : "Run sequence"}
        </Button>
      </div>
      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground">
          Advanced
        </summary>
        <div className="mt-3 space-y-3">
          <Label htmlFor="playground-python">Optimizer Python executable</Label>
          <Input
            id="playground-python"
            value={python}
            placeholder="Default"
            onChange={(e) => setPython(e.target.value)}
          />
          <Label htmlFor="playground-advanced">Optimizer settings (JSON)</Label>
          <Textarea
            id="playground-advanced"
            value={advanced}
            onChange={(e) => setAdvanced(e.target.value)}
            className="font-mono"
          />
          {catalog?.errors.map((e) => (
            <p key={e.file} role="alert">
              {e.file}: {e.error}
            </p>
          ))}
        </div>
      </details>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
