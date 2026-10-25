"use client";
import { useState } from "react";
import { useDemo } from "@/components/DemoDesk";
import { Dashboard } from "@/components/Dashboard";
import { SetupWizard } from "@/components/SetupWizard";
import { markSetupDone, resetSetup, useSetupDone } from "@/lib/setup";

// First run: the setup wizard. Once it is finished, open straight to the
// dashboard; "Re-run setup" clears the flag.
export default function Home() {
  const demo = useDemo();
  const done = useSetupDone();
  const [startId, setStartId] = useState<string | undefined>();
  if (done === null) return <main aria-busy="true" />;
  if (!done)
    return (
      <SetupWizard
        demo={demo}
        onDone={(id) => {
          setStartId(id);
          markSetupDone();
        }}
      />
    );
  return (
    <Dashboard demo={demo} initialId={startId} onRerunSetup={resetSetup} />
  );
}
