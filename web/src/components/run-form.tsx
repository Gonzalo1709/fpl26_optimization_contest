import { useState, type FormEvent } from "react"
import { LoaderCircle, Play, Terminal } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { api, type Configuration, type Fields, type Settings } from "@/lib/api"

export function RunForm({
  settings,
  initial,
  onQueued,
}: {
  settings: Settings
  initial?: Configuration
  onQueued: (id: string) => void
}) {
  const [config, setConfig] = useState(initial || settings.defaults)
  const [advanced, setAdvanced] = useState(
    JSON.stringify(config.advanced, null, 2)
  )
  const [error, setError] = useState("")
  const [busy, setBusy] = useState("")
  const [preview, setPreview] = useState<string[] | null>(null)
  const [probe, setProbe] = useState<Fields | null>(null)
  function update<K extends keyof Configuration>(
    key: K,
    value: Configuration[K]
  ) {
    setConfig((c) => ({ ...c, [key]: value }))
    setPreview(null)
    setProbe(null)
  }
  function payload() {
    const parsed: unknown = JSON.parse(advanced)
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
      throw new Error("Advanced settings must be a JSON object")
    const body = { ...config }
    delete body.schema_version
    return { ...body, advanced: parsed }
  }
  async function perform(action: string) {
    setBusy(action)
    setError("")
    try {
      const body = payload()
      if (action === "enqueue")
        onQueued((await api<{ job_id: string }>("/jobs", body)).job_id)
      else if (action === "preview")
        setPreview(
          (await api<{ argv: string[] }>("/configuration/preview", body)).argv
        )
      else setProbe(await api<Fields>("/configuration/check", body))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy("")
    }
  }
  function submit(e: FormEvent) {
    e.preventDefault()
    void perform("enqueue")
  }
  return (
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle className="text-lg">New experiment</DialogTitle>
        <DialogDescription>
          Configure an optimizer job. Execution continues independently of this
          browser.
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="space-y-5">
        <div className="space-y-2">
          <Label htmlFor="input-dcp">Input checkpoint</Label>
          <Input
            id="input-dcp"
            value={config.input_dcp}
            onChange={(e) => update("input_dcp", e.target.value)}
            placeholder="Absolute path to design.dcp on the execution host"
            required
          />
          <p className="text-xs text-muted-foreground">
            Paths refer to the machine running the framework.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="mode">Mode</Label>
            <select
              id="mode"
              value={config.mode}
              onChange={(e) => update("mode", e.target.value)}
            >
              {["deterministic", "llm", "single", "test"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="profile">Budget profile</Label>
            <select
              id="profile"
              value={config.profile}
              onChange={(e) => update("profile", e.target.value)}
            >
              {settings.profiles.map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="runtime">Runtime limit (minutes)</Label>
            <Input
              id="runtime"
              type="number"
              min="0.01"
              step="any"
              required
              value={config.max_runtime_minutes}
              onChange={(e) =>
                update("max_runtime_minutes", Number(e.target.value))
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cost">Cost limit (USD, optional)</Label>
            <Input
              id="cost"
              type="number"
              min="0.01"
              step="any"
              value={config.max_cost ?? ""}
              onChange={(e) =>
                update(
                  "max_cost",
                  e.target.value ? Number(e.target.value) : null
                )
              }
            />
          </div>
        </div>
        {config.mode === "llm" && (
          <div className="space-y-2">
            <Label htmlFor="model">Model</Label>
            <Input
              id="model"
              required
              value={config.model}
              onChange={(e) => update("model", e.target.value)}
              placeholder="Provider/model identifier"
            />
            <p className="text-xs text-muted-foreground">
              Uses OPENROUTER_API_KEY from the execution host's environment.
            </p>
          </div>
        )}
        {config.mode === "single" && (
          <div className="space-y-2">
            <Label htmlFor="method">Method</Label>
            <select
              id="method"
              value={config.method}
              onChange={(e) => update("method", e.target.value)}
            >
              {settings.methods.map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </div>
        )}
        <details className="border p-3">
          <summary className="cursor-pointer text-xs font-medium">
            Advanced settings
          </summary>
          <div className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="python">Optimizer Python executable</Label>
              <Input
                id="python"
                required
                value={config.python}
                onChange={(e) => update("python", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="advanced">Optimizer options (JSON)</Label>
              <Textarea
                id="advanced"
                className="min-h-28 font-mono"
                value={advanced}
                onChange={(e) => {
                  setAdvanced(e.target.value)
                  setPreview(null)
                  setProbe(null)
                }}
              />
            </div>
          </div>
        </details>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        {probe && (
          <details open>
            <summary className="text-xs">Environment probe</summary>
            <pre className="json-block mt-2">
              {JSON.stringify(probe, null, 2)}
            </pre>
          </details>
        )}
        {preview && (
          <div>
            <p className="mb-2 text-xs font-medium">
              Argument preview (paths assigned when queued)
            </p>
            <pre className="json-block">
              {preview.map((arg) => JSON.stringify(arg)).join(" ")}
            </pre>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <div className="flex gap-2">
            <Button
              variant="outline"
              type="button"
              disabled={!!busy}
              onClick={() => void perform("preview")}
            >
              <Terminal />
              Preview
            </Button>
            <Button
              variant="ghost"
              type="button"
              disabled={!!busy}
              onClick={() => void perform("check")}
            >
              Check environment
            </Button>
          </div>
          <Button type="submit" disabled={!!busy}>
            {busy ? <LoaderCircle className="animate-spin" /> : <Play />}Enqueue
            experiment
          </Button>
        </div>
      </form>
    </DialogContent>
  )
}
