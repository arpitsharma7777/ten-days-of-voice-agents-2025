"use client";

import React, { useState, useEffect } from "react";

export const OrderVisualizer = () => {
  const [order, setOrder] = useState<any>(null);

  useEffect(() => {
    const interval = setInterval(() => {
      fetch("/api/order-state")
        .then(res => res.json())
        .then(data => setOrder(data))
        .catch(() => {});
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  if (!order) {
    return (
      <div className="p-4 text-center text-gray-500">
        No order yet...
      </div>
    );
  }

  return (
    <div className="bg-white shadow-xl rounded-xl p-6 mt-4">
      <h2 className="text-xl font-bold mb-3">Your Order</h2>

      <p>☕ <strong>Drink:</strong> {order.drinkType}</p>
      <p>📏 <strong>Size:</strong> {order.size}</p>
      <p>🥛 <strong>Milk:</strong> {order.milk}</p>

      <p>
        🎯 <strong>Extras:</strong> {order.extras?.join(", ") || "No extras"}
      </p>

      <p>👤 <strong>Name:</strong> {order.name}</p>
    </div>
  );
};
