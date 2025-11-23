import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

export async function GET() {
  try {
    // backend/orders folder तक path लो
    const ordersDir = path.join(process.cwd(), "..", "backend", "orders");

    // JSON files पढ़ो
    const files = fs.readdirSync(ordersDir)
      .filter(f => f.endsWith(".json"))
      .sort()
      .reverse();

    if (files.length === 0) {
      return NextResponse.json({});
    }

    // latest order पढ़ो
    const latest = path.join(ordersDir, files[0]);
    const json = JSON.parse(fs.readFileSync(latest, "utf8"));

    return NextResponse.json(json);

  } catch (e) {
    console.error(e);
    return NextResponse.json({});
  }
}
