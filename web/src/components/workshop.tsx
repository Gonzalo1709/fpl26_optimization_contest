import { useEffect, useState } from "react"
import { ArrowDown, ArrowUp, Plus, Trash2, Play, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  activeStatuses,
  api,
  number,
  type SearchNode,
  type Snapshot,
} from "@/lib/api"

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
export function Workshop({
  snapshot,
  node,
  onShowBranch,
}: {
  snapshot: Snapshot
  node: SearchNode | undefined
  onShowBranch: (id: string) => void
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
  const [createdRun, setCreatedRun] = useState("")
  const [dragged, setDragged] = useState<number | null>(null)
  useEffect(() => {
    let current = true
    api<Catalog>("/recipes")
      .then((recipes) => {
        if (current) {
          setCatalog(recipes)
        }
      })
      .catch((e: Error) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [snapshot.id])
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
        `/runs/${node?.source_run_key || snapshot.id}/playground`,
        {
          candidate_id:
            node?.candidate_id || node?.local_node_id || node?.node_id,
          steps: steps.map(({ strategy, args }) => ({ strategy, args })),
          max_runtime_minutes: runtime,
          ...(python.trim() ? { python: python.trim() } : {}),
          advanced: JSON.parse(advanced),
        }
      )
      setCreatedRun(result.job_id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-4 p-4">
      <div className="space-y-1 border-b pb-3">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-xs font-medium">
            {node?.strategy ||
              (node?.parent_node_id ? "Checkpoint" : "Baseline")}
          </span>
          <span className="shrink-0 font-mono text-xs">
            {number(node?.fmax_mhz, 1)} MHz
          </span>
        </div>
        <p
          className="truncate font-mono text-[10px] text-muted-foreground"
          data-testid="workshop-source"
          title={node?.local_node_id || node?.node_id}
        >
          {node?.node_type === "manual_execution"
            ? "Manual experiment"
            : node?.local_node_id || node?.node_id || "No node selected"}
        </p>
        {!node?.can_run_from && (
          <p className="text-xs text-muted-foreground">
            {node?.checkpoint_unavailable_reason ||
              "This node has no saved checkpoint"}
          </p>
        )}
        {node?.manual && (
          <div className="flex items-center justify-between text-xs text-sky-700 dark:text-sky-300">
            <span>Manual · {node.job_status?.replaceAll("_", " ")}</span>
            {node.job_id && activeStatuses.has(node.job_status || "") && (
              <Button
                variant="ghost"
                size="xs"
                onClick={() =>
                  void api(`/jobs/${node.job_id}/cancel`, {}).catch(
                    (e: Error) => setError(e.message)
                  )
                }
              >
                Cancel experiment
              </Button>
            )}
          </div>
        )}
        {node?.job_error && (
          <p role="alert" className="text-xs text-destructive">
            {node.job_error}
          </p>
        )}
      </div>
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1 space-y-2">
          <Label htmlFor="workshop-recipe">Recipe</Label>
          <select
            id="workshop-recipe"
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
          size="icon"
          aria-label="Add recipe"
          title="Add recipe"
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
          <Plus />
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
            <div className="grid gap-3">
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
          <Label htmlFor="workshop-runtime">Time limit (min)</Label>
          <Input
            id="workshop-runtime"
            type="number"
            min="1"
            value={runtime}
            onChange={(e) => setRuntime(Number(e.target.value))}
          />
        </div>
        <Button
          disabled={
            busy || !steps.length || !node?.can_run_from || runtime <= 0
          }
          onClick={() => void run()}
        >
          <Play /> {busy ? "Queuing…" : "Run sequence"}
        </Button>
      </div>
      {createdRun && (
        <div
          role="status"
          className="flex items-center justify-between text-xs text-muted-foreground"
        >
          <span>Run created</span>
          <Button variant="link" onClick={() => onShowBranch(createdRun)}>
            Show branch
          </Button>
        </div>
      )}
      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground">
          Advanced
        </summary>
        <div className="mt-3 space-y-3">
          <Label htmlFor="workshop-python">Optimizer Python executable</Label>
          <Input
            id="workshop-python"
            value={python}
            placeholder="Default"
            onChange={(e) => setPython(e.target.value)}
          />
          <Label htmlFor="workshop-advanced">Optimizer settings (JSON)</Label>
          <Textarea
            id="workshop-advanced"
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
