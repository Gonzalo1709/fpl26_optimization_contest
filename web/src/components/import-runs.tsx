import { useState, type FormEvent } from "react"
import {
  ArrowRight,
  FileArchive,
  FolderOpen,
  LoaderCircle,
  Upload,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, uploadBundle } from "@/lib/api"

export function ImportRuns({
  onImported,
}: {
  onImported: (id: string) => void
}) {
  const [file, setFile] = useState<File>()
  const [folder, setFolder] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  async function upload(e: FormEvent) {
    e.preventDefault()
    setError("")
    if (!file) {
      setError("Choose an analysis ZIP first")
      return
    }
    if (file.size > 64 * 1024 * 1024) {
      setError(
        "The ZIP must be 64 MiB or smaller. Export fewer runs per archive."
      )
      return
    }
    setBusy(true)
    try {
      onImported((await uploadBundle(file)).id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  async function open(e: FormEvent) {
    e.preventDefault()
    setError("")
    setBusy(true)
    try {
      onImported((await api<{ id: string }>("/runs/open", { path: folder })).id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle className="text-lg">Import or open runs</DialogTitle>
        <DialogDescription>
          Bring a cloud experiment into this workspace, or open logs already on
          the UI host.
        </DialogDescription>
      </DialogHeader>
      <Tabs defaultValue="upload" onValueChange={() => setError("")}>
        <TabsList className="w-full">
          <TabsTrigger value="upload">
            <Upload />
            Upload cloud ZIP
          </TabsTrigger>
          <TabsTrigger value="folder">
            <FolderOpen />
            Open host folder
          </TabsTrigger>
          <TabsTrigger value="export">
            <FileArchive />
            How to export
          </TabsTrigger>
        </TabsList>
        <TabsContent value="upload" className="space-y-4 pt-4">
          <div className="border bg-muted/40 p-4">
            <h3 className="mb-2 text-sm font-medium">
              Cloud run → analysis ZIP → local inspector
            </h3>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Upload the ZIP exported on your cloud instance. Each run gets its
              own folder with events, summaries, and decision/tool evidence. DCP
              checkpoints and FPGA tools are not needed for analysis.
            </p>
          </div>
          <form onSubmit={upload} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="analysis-zip">Analysis ZIP file</Label>
              <Input
                id="analysis-zip"
                type="file"
                accept=".zip,application/zip"
                disabled={busy}
                onChange={(e) => {
                  setFile(e.target.files?.[0])
                  setError("")
                }}
              />
              <p className="text-xs text-muted-foreground">
                One or multiple runs · 64 MiB maximum · files stay on this UI
                host
              </p>
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Imported runs are saved snapshots. They remain available after a
              restart and cannot control or resume the cloud job. An
              events.jsonl file alone can be missing the referenced planner/tool
              evidence; export the complete analysis ZIP.
            </p>
            {error && (
              <p className="error-banner" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" disabled={busy || !file}>
              {busy ? <LoaderCircle className="animate-spin" /> : <Upload />}
              {busy ? "Importing…" : "Import ZIP"}
            </Button>
          </form>
        </TabsContent>
        <TabsContent value="folder" className="space-y-4 pt-4">
          <p className="text-xs leading-relaxed text-muted-foreground">
            Use this when the logs are already on the machine running this web
            UI. Enter a run folder, its events.jsonl path, or a parent
            containing run folders. This opens files in place; it does not copy
            from a cloud instance.
          </p>
          <form onSubmit={open} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="run-folder">
                Folder or events.jsonl path on the UI host
              </Label>
              <Input
                id="run-folder"
                value={folder}
                onChange={(e) => setFolder(e.target.value)}
                placeholder="Absolute path on the UI host"
                required
              />
            </div>
            <p className="text-xs text-muted-foreground">
              The inspector can follow new writes to this folder. A copied cloud
              folder updates only when you copy more data.
            </p>
            {error && (
              <p className="error-banner" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" disabled={busy}>
              {busy ? (
                <LoaderCircle className="animate-spin" />
              ) : (
                <FolderOpen />
              )}
              Open folder
            </Button>
          </form>
        </TabsContent>
        <TabsContent value="export" className="space-y-4 pt-4">
          <ol className="space-y-4 text-xs leading-relaxed">
            <li>
              <strong>
                1. Run your usual optimizer command on the cloud instance.
              </strong>
              <p className="mt-1 text-muted-foreground">
                The CLI prints its run directory. Optionally add{" "}
                <code>--run-dir /path/runs/experiment-01</code> to choose a new
                or empty folder. Use a version of the framework with deep run
                logging.
              </p>
            </li>
            <li>
              <strong>
                2. After the run finishes or stops, export from the repository
                root.
              </strong>
              <pre className="json-block mt-2">
                {
                  "python -m tools.run_bundle export /path/runs/experiment-01 --out experiment-01.zip"
                }
              </pre>
              <p className="mt-2 text-muted-foreground">
                For a batch, list multiple run folders before{" "}
                <code>--out batch.zip</code>. Failed runs with readable logs can
                be analyzed too.
              </p>
            </li>
            <li>
              <strong>3. Copy the ZIP to your computer.</strong>
              <pre className="json-block mt-2">
                {"scp YOUR_SSH_ALIAS:/path/to/experiment-01.zip ."}
              </pre>
              <p className="mt-2 text-muted-foreground">
                You can also use your usual file transfer tool. No cloud
                connection credentials are stored in this UI.
              </p>
            </li>
            <li>
              <strong>4. Choose Upload cloud ZIP → Import ZIP.</strong>
              <p className="mt-1 text-muted-foreground">
                Select any imported run in the sidebar to inspect branches,
                decisions, and evidence.
              </p>
            </li>
          </ol>
          <div className="flex items-start gap-2 border-t pt-4 text-xs text-muted-foreground">
            <ArrowRight className="mt-0.5 size-3.5 shrink-0" />
            <p>
              Need live cloud monitoring? Run this UI on the cloud instance and
              access it through SSH port forwarding. Uploading a ZIP is snapshot
              analysis.
            </p>
          </div>
        </TabsContent>
      </Tabs>
    </DialogContent>
  )
}
