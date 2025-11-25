import { NextResponse } from "next/server";
import path from "path";
import fs from "fs/promises";

export const revalidate = 0;

export async function GET() {
  try {
    const logPath = path.join(
      process.cwd(),
      "..",
      "backend",
      "tutor",
      "tutor_progress.json"
    );

    const data = await fs.readFile(logPath, "utf-8");
    const json = JSON.parse(data);

    return NextResponse.json(json, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    // file abhi nahi bana hai toh empty object bhej do
    return NextResponse.json({}, { status: 200 });
  }
}
