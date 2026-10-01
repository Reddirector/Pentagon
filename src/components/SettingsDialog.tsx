import { api } from "@/convex/_generated/api";
import {
  Download,
  LogOut,
  RotateCcw,
  Settings2,
  Trash2,
  User,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "convex/react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

export type ChatSettings = {
  temperature: number;
  topP: number;
  maxTokens: number;
  customInstructions: string;
  sendWithEnter: boolean;
  webSearch: boolean;
};

export const DEFAULT_SETTINGS: ChatSettings = {
  temperature: 1,
  topP: 0.95,
  maxTokens: 16384,
  customInstructions: "",
  sendWithEnter: true,
  webSearch: true,
};

const MAX_INSTRUCTIONS = 2000;

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  settings: ChatSettings;
  onSettingsChange: (next: ChatSettings) => void;
  userName: string;
  onSignOut: () => void;
  onDeletedAll: () => void;
};

function SectionTitle({
  icon: Icon,
  children,
}: {
  icon: typeof Settings2;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex size-6 items-center justify-center rounded-lg bg-primary/15 text-primary">
        <Icon className="size-3.5" />
      </div>
      <h3 className="text-xs font-semibold uppercase tracking-[0.2em]">
        {children}
      </h3>
    </div>
  );
}

export default function SettingsDialog({
  open,
  onOpenChange,
  settings,
  onSettingsChange,
  userName,
  onSignOut,
  onDeletedAll,
}: Props) {
  const clearAll = useMutation(api.chats.clearAllChats);
  const data = useQuery(api.chats.exportAll, open ? {} : "skip");
  const [confirmText, setConfirmText] = useState("");
  const [dangerOpen, setDangerOpen] = useState(false);
  const [clearing, setClearing] = useState(false);

  // Reset the confirmation input whenever the danger dialog closes.
  useEffect(() => {
    if (!dangerOpen) setConfirmText("");
  }, [dangerOpen]);

  const set = <K extends keyof ChatSettings>(key: K, value: ChatSettings[K]) =>
    onSettingsChange({ ...settings, [key]: value });

  const chatCount = data?.chats.length ?? 0;
  const messageCount =
    data?.chats.reduce((acc, c) => acc + c.messages.length, 0) ?? 0;

  const downloadExport = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `pentagon-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${chatCount} chats`);
  };

  const handleClearAll = async () => {
    setClearing(true);
    try {
      const n = await clearAll({});
      toast.success(`Deleted ${n} ${n === 1 ? "chat" : "chats"} and all messages.`);
      setDangerOpen(false);
      onDeletedAll();
      onOpenChange(false);
    } catch {
      toast.error("Failed to delete chats. Try again.");
    } finally {
      setClearing(false);
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-h-[85vh] max-w-lg gap-0 overflow-y-auto ptg-scroll rounded-2xl border-border bg-card p-0 shadow-2xl shadow-black/50">
          <DialogHeader className="rounded-t-2xl px-5 py-4 ptg-border-b">
            <DialogTitle className="flex items-center gap-2.5 text-sm font-semibold tracking-wide">
              <span className="flex size-7 items-center justify-center rounded-lg bg-primary/15 text-primary">
                <Settings2 className="size-4" />
              </span>
              Settings
            </DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">
              Model behavior · history · data
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-5 px-5 py-5">
            {/* Model */}
            <section className="flex flex-col gap-4">
              <SectionTitle icon={Settings2}>Model</SectionTitle>

              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs font-medium text-muted-foreground">
                    Temperature
                  </Label>
                  <span className="rounded-md bg-accent px-2 py-0.5 text-xs font-semibold">
                    {settings.temperature.toFixed(2)}
                  </span>
                </div>
                <Slider
                  value={[settings.temperature]}
                  min={0}
                  max={2}
                  step={0.05}
                  onValueChange={([v]) => set("temperature", v)}
                />
                <p className="text-[10px] text-muted-foreground">
                  Lower = focused · higher = creative
                </p>
              </div>

              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs font-medium text-muted-foreground">
                    Top P
                  </Label>
                  <span className="rounded-md bg-accent px-2 py-0.5 text-xs font-semibold">
                    {settings.topP.toFixed(2)}
                  </span>
                </div>
                <Slider
                  value={[settings.topP]}
                  min={0.05}
                  max={1}
                  step={0.05}
                  onValueChange={([v]) => set("topP", v)}
                />
              </div>

              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs font-medium text-muted-foreground">
                    Max response tokens
                  </Label>
                  <span className="rounded-md bg-accent px-2 py-0.5 text-xs font-semibold">
                    {settings.maxTokens.toLocaleString()}
                  </span>
                </div>
                <Slider
                  value={[settings.maxTokens]}
                  min={512}
                  max={16384}
                  step={512}
                  onValueChange={([v]) => set("maxTokens", v)}
                />
                <p className="text-[10px] text-muted-foreground">
                  Reasoning tokens count toward this budget
                </p>
              </div>

              <div className="flex flex-col gap-2">
                <Label className="text-xs font-medium text-muted-foreground">
                  Custom instructions
                </Label>
                <Textarea
                  value={settings.customInstructions}
                  onChange={(e) =>
                    set("customInstructions", e.target.value.slice(0, MAX_INSTRUCTIONS))
                  }
                  placeholder="e.g. Always answer in bullet points. You are a witty assistant…"
                  className="min-h-20 resize-none rounded-xl border-border bg-background/60 text-sm"
                />
                <p className="text-right text-[10px] text-muted-foreground">
                  {settings.customInstructions.length}/{MAX_INSTRUCTIONS}
                </p>
              </div>

              <div className="flex items-center justify-between rounded-xl bg-accent/50 px-3 py-2.5 ptg-border">
                <div>
                  <p className="text-xs font-medium">Enter to send</p>
                  <p className="text-[10px] text-muted-foreground">
                    Shift+Enter always makes a newline
                  </p>
                </div>
                <Switch
                  checked={settings.sendWithEnter}
                  onCheckedChange={(v) => set("sendWithEnter", v)}
                />
              </div>

              <div className="flex items-center justify-between rounded-xl bg-accent/50 px-3 py-2.5 ptg-border">
                <div>
                  <p className="text-xs font-medium">Web search (RAG)</p>
                  <p className="text-[10px] text-muted-foreground">
                    Model can search the web and read pages · Tavily +
                    Firecrawl
                  </p>
                </div>
                <Switch
                  checked={settings.webSearch}
                  onCheckedChange={(v) => set("webSearch", v)}
                />
              </div>

              <Button
                variant="outline"
                size="sm"
                className="self-start gap-2 rounded-full border-border bg-transparent text-xs font-medium hover:bg-accent"
                onClick={() => {
                  onSettingsChange({ ...DEFAULT_SETTINGS });
                  toast.success("Model settings reset to defaults");
                }}
              >
                <RotateCcw className="size-3.5" />
                Reset model settings
              </Button>
            </section>

            <Separator className="bg-border" />

            {/* History / data */}
            <section className="flex flex-col gap-3">
              <SectionTitle icon={Download}>Chat history</SectionTitle>
              <p className="text-xs text-muted-foreground">
                {chatCount} {chatCount === 1 ? "chat" : "chats"} ·{" "}
                {messageCount.toLocaleString()}{" "}
                {messageCount === 1 ? "message" : "messages"} stored. Images are
                not included in exports.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-2 rounded-full border-border bg-transparent text-xs font-medium hover:bg-accent"
                  disabled={!data}
                  onClick={downloadExport}
                >
                  <Download className="size-3.5" />
                  Export JSON
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-2 rounded-full border-destructive/40 bg-destructive/10 text-xs font-medium text-destructive hover:bg-destructive hover:text-white"
                  disabled={chatCount === 0}
                  onClick={() => setDangerOpen(true)}
                >
                  <Trash2 className="size-3.5" />
                  Delete all chats
                </Button>
              </div>
            </section>

            <Separator className="bg-border" />

            {/* Account */}
            <section className="flex flex-col gap-3">
              <SectionTitle icon={User}>Account</SectionTitle>
              <div className="flex items-center justify-between rounded-xl bg-accent/50 px-3 py-2.5 ptg-border">
                <span className="truncate text-xs font-medium">{userName}</span>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-2 rounded-full border-border bg-transparent text-xs font-medium hover:bg-accent"
                  onClick={onSignOut}
                >
                  <LogOut className="size-3.5" />
                  Sign out
                </Button>
              </div>
            </section>
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete-all confirmation */}
      <AlertDialog open={dangerOpen} onOpenChange={setDangerOpen}>
        <AlertDialogContent className="max-w-md gap-0 rounded-2xl border-border bg-card p-0 shadow-2xl shadow-black/50">
          <AlertDialogHeader className="rounded-t-2xl px-5 py-4 ptg-border-b">
            <AlertDialogTitle className="text-sm font-semibold tracking-wide">
              Delete all chats?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-xs text-muted-foreground">
              {chatCount} {chatCount === 1 ? "chat" : "chats"} and{" "}
              {messageCount.toLocaleString()}{" "}
              {messageCount === 1 ? "message" : "messages"} will be permanently
              removed. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="flex flex-col gap-3 px-5 py-4">
            <Label className="text-xs font-medium text-muted-foreground">
              Type DELETE to confirm
            </Label>
            <input
              autoFocus
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value.toUpperCase())}
              placeholder="DELETE"
              className="w-full rounded-xl border-border bg-background/60 px-3 py-2 text-sm font-semibold tracking-widest outline-none ring-border transition focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <AlertDialogFooter className="gap-2 px-5 py-4 ptg-border-t">
            <AlertDialogCancel className="rounded-full border-border bg-transparent text-xs font-medium hover:bg-accent">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={confirmText !== "DELETE" || clearing}
              onClick={(e) => {
                e.preventDefault();
                void handleClearAll();
              }}
              className="rounded-full bg-destructive text-xs font-semibold text-white hover:bg-destructive/90"
            >
              {clearing ? "Deleting…" : "Delete everything"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
