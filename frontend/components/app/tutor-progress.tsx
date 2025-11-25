"use client";

import React, { useEffect, useState } from "react";

type ProgressMap = {
  [conceptId: string]: {
    learn: number;
    quiz: number;
    teach_back: number;
    last_updated?: string;
  };
};

const CONCEPT_LABELS: Record<string, string> = {
  variables: "Variables",
  loops: "Loops",
  conditions: "Conditionals",
};

export const TutorProgress: React.FC = () => {
  const [progress, setProgress] = useState<ProgressMap>({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const fetchData = () => {
      fetch("/api/tutor-progress")
        .then((res) => res.json())
        .then((data) => {
          setProgress(data || {});
          setLoaded(true);
        })
        .catch(() => setLoaded(true));
    };

    fetchData();
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, []);

  if (!loaded) {
    return (
      <div className="mt-4 text-sm text-muted-foreground">
        Loading tutor progress…
      </div>
    );
  }

  const conceptIds = Object.keys(progress);
  if (conceptIds.length === 0) {
    return (
      <div className="mt-4 rounded-xl border bg-white/60 p-4 shadow-sm text-sm text-muted-foreground">
        No tutor activity recorded yet. Start a session and learn, quiz, or
        teach back a concept to see progress here.
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-xl border bg-white/70 p-4 shadow-md max-w-3xl">
      <h2 className="mb-3 text-lg font-semibold">Tutor Progress</h2>
      <p className="mb-4 text-xs text-muted-foreground">
        Tracks how many times you have learned, been quizzed, or taught back
        each concept in this browser.
      </p>

      <div className="space-y-3">
        {conceptIds.map((id) => {
          const entry = progress[id];
          const label = CONCEPT_LABELS[id] ?? id;

          return (
            <div
              key={id}
              className="flex flex-col gap-2 rounded-lg bg-slate-50 p-3 md:flex-row md:items-center md:justify-between"
            >
              <div>
                <div className="text-sm font-medium">{label}</div>
                {entry.last_updated && (
                  <div className="text-xs text-muted-foreground">
                    Last activity: {entry.last_updated.split("T")[0]}
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-2 text-xs">
                <Badge count={entry.learn} label="Learn" />
                <Badge count={entry.quiz} label="Quiz" />
                <Badge count={entry.teach_back} label="Teach-back" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Badge: React.FC<{ label: string; count: number }> = ({ label, count }) => {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium shadow-sm">
      <span>{label}</span>
      <span className="rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-bold text-white">
        {count}
      </span>
    </span>
  );
};
