import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

export async function GET() {
  try {
    // backend/orders folder
    const ordersDir = path.join(process.cwd(), "..", "backend", "orders");

    // list JSON files
    const files = fs.readdirSync(ordersDir)
      .filter(f => f.endsWith(".json"))
      .sort()      // earliest → latest
      .reverse();  // latest becomes first

    if (files.length === 0) {
      return NextResponse.json({
        hasOrder: false,
        message: "No orders found yet.",
      });
    }

    // Read latest order file
    const latest = path.join(ordersDir, files[0]);
    const orderData = JSON.parse(fs.readFileSync(latest, "utf8"));

    // Build summary response
    const summary = {
      hasOrder: true,
      orderId: orderData.orderId,
      timestamp: orderData.timestamp,
      status: orderData.status || "received",
      total: orderData.total || 0,
      items: orderData.items || [],
    };

    return NextResponse.json(summary);

  } catch (error) {
    console.error("Order Summary API Error:", error);
    return NextResponse.json({
      hasOrder: false,
      error: "Could not load order summary",
    });
  }
}
