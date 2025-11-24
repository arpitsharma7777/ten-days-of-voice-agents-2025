import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

export async function GET() {
  try {
    // Correct absolute path → points to backend/wellness/wellness_log.json
    const logPath = path.join(process.cwd(), "..", "backend", "wellness", "wellness_log.json");

    const file = fs.readFileSync(logPath, "utf8");
    const data = JSON.parse(file);

    // Return **last entry only**
    return NextResponse.json(data[data.length - 1] || {});
  } catch (e) {
    return NextResponse.json({ error: "No log found" }, { status: 404 });
  }
}
