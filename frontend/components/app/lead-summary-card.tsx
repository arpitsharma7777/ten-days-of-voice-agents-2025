"use client";

import React, { useEffect, useState } from "react";

type LeadPayload = {
  timestamp: string;
  summary: string;
  lead: {
    name?: string | null;
    company?: string | null;
    email?: string | null;
    role?: string | null;
    use_case?: string | null;
    team_size?: string | null;
    timeline?: string | null;
  };
};

export const LeadSummaryCard: React.FC = () => {
  const [data, setData] = useState<LeadPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchLead = async () => {
      try {
        const res = await fetch("/api/lead-summary");
        if (!res.ok) {
          setError("No lead captured yet.");
          setData(null);
          return;
        }
        const json = (await res.json()) as LeadPayload;
        setData(json);
        setError(null);
      } catch {
        setError("Unable to load latest lead.");
      }
    };

    fetchLead();
    const id = setInterval(fetchLead, 3000);
    return () => clearInterval(id);
  }, []);

  if (error) {
    return (
      <div className="mt-4 mx-auto max-w-2xl rounded-xl border bg-white/70 p-4 text-sm text-muted-foreground shadow-sm">
        {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mt-4 mx-auto max-w-2xl rounded-xl border bg-white/70 p-4 text-sm text-muted-foreground shadow-sm">
        Waiting for a lead... Talk to the SDR agent to generate one.
      </div>
    );
  }

  const { lead } = data;

  return (
    <div className="mt-4 mx-auto max-w-2xl rounded-2xl border bg-white/80 p-5 shadow-lg backdrop-blur">
      <h2 className="text-lg font-semibold tracking-tight mb-3">
        Lead Summary
      </h2>
      <p className="text-xs text-muted-foreground mb-4">
        Captured at{" "}
        {new Date(data.timestamp).toLocaleString(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
        })}
      </p>

      <div className="space-y-1 text-sm">
        <p>
          <span className="font-medium">👤 Name:</span>{" "}
          {lead.name || "—"}
        </p>
        <p>
          <span className="font-medium">🏢 Company:</span>{" "}
          {lead.company || "—"}
        </p>
        <p>
          <span className="font-medium">📧 Email:</span>{" "}
          {lead.email || "—"}
        </p>
        <p>
          <span className="font-medium">🎓 Role:</span>{" "}
          {lead.role || "—"}
        </p>
        <p>
          <span className="font-medium">🧩 Use case:</span>{" "}
          {lead.use_case || "—"}
        </p>
        <p>
          <span className="font-medium">👥 Team size:</span>{" "}
          {lead.team_size || "—"}
        </p>
        <p>
          <span className="font-medium">⏱ Timeline:</span>{" "}
          {lead.timeline || "—"}
        </p>
      </div>

      <div className="mt-4 border-t pt-3 text-sm">
        <p className="font-medium mb-1">📝 SDR Summary</p>
        <p className="text-muted-foreground">{data.summary}</p>
      </div>
    </div>
  );
};
