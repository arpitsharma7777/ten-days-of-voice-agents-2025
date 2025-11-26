import { NextResponse } from "next/server";
import path from "path";
import { promises as fs } from "fs";

export const revalidate = 0;

export async function GET() {
  try {
    const logPath = path.join(
      process.cwd(),
      "..",
      "backend",
      "leads",
      "latest_lead.json"
    );

    const data = await fs.readFile(logPath, "utf-8");
    const json = JSON.parse(data);

    return NextResponse.json(json, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: "No lead captured yet." },
      { status: 404 }
    );
  }
}
