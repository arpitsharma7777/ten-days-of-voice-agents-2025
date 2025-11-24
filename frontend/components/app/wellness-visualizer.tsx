"use client";

import React, { useEffect, useState } from "react";

export const WellnessVisualizer = () => {
  const [log, setLog] = useState<any>(null);

  useEffect(() => {
    const interval = setInterval(() => {
      fetch("/api/wellness-log")
        .then((res) => res.json())
        .then((data) => {
          if (!data.error) setLog(data);
        })
        .catch(() => {});
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  if (!log) {
    return (
      <div className="text-gray-400 text-center mt-4 italic">
        No wellness check-in yet...
      </div>
    );
  }

  return (
    <div className="bg-white shadow-xl rounded-xl p-5 mt-6 border max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">Wellness Summary</h2>

      <p>
        <b>🗓 Date:</b> {log.timestamp?.split("T")[0] || "N/A"}
      </p>

      <p>
        <b>🙂 Mood:</b> {log.mood || "N/A"}
      </p>

      <p>
        <b>⚡ Energy:</b> {log.energy || "N/A"}
      </p>

      <p>
        <b>😟 Stress:</b> {log.stress || "N/A"}
      </p>

      <p>
        <b>🎯 Goals:</b>{" "}
        {log.goals?.length ? log.goals.join(", ") : "No goals today"}
      </p>

      <p className="mt-3">
        <b>📝 Summary:</b> {log.summary || "No summary recorded"}
      </p>
    </div>
  );
};
