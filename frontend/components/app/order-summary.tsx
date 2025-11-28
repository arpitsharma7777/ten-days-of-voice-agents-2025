"use client";

import { useState } from "react";

interface CartItem {
  name: string;
  qty: number;
  price: number;
}

export default function OrderSummaryCard() {
  const [cart, setCart] = useState<CartItem[]>([]);

  const total = cart.reduce((t, item) => t + item.price * item.qty, 0);

  const addItem = (name: string, price: number, qty = 1) => {
    setCart(prev => {
      const exists = prev.find(i => i.name === name);
      if (exists) {
        return prev.map(i =>
          i.name === name ? { ...i, qty: i.qty + qty } : i
        );
      }
      return [...prev, { name, price, qty }];
    });
  };

  const placeOrder = () => {
    console.log("Order placed:", cart);
    alert("Order placed! Check console for JSON output.");
  };

  return (
    <div className="w-full max-w-sm mx-auto p-4">
      <div className="bg-white rounded-2xl shadow-md p-5 border border-gray-200">
        
        <h2 className="text-xl font-semibold text-gray-800 mb-3">
          🛒 Order Summary
        </h2>

        <div className="space-y-2 text-gray-700 text-sm">
          {cart.length === 0 ? (
            <p className="text-gray-400">Your cart is empty...</p>
          ) : (
            cart.map((item, idx) => (
              <div key={idx} className="flex justify-between">
                <span>{item.name} × {item.qty}</span>
                <span>₹{item.price * item.qty}</span>
              </div>
            ))
          )}
        </div>

        <hr className="my-4" />

        <div className="flex justify-between text-lg font-bold text-gray-800">
          <span>Total</span>
          <span>₹{total}</span>
        </div>

        <button
          onClick={placeOrder}
          className="w-full mt-4 py-2 bg-green-600 text-white rounded-xl font-semibold hover:bg-green-700 transition"
        >
          Place Order
        </button>

        {/* testing buttons (remove later) */}
        <div className="mt-4 space-x-2 text-xs">
          <button
            onClick={() => addItem("Milk 1L", 55)}
            className="px-2 py-1 bg-gray-100 rounded"
          >
            + Milk
          </button>
          <button
            onClick={() => addItem("Bread", 40)}
            className="px-2 py-1 bg-gray-100 rounded"
          >
            + Bread
          </button>
          <button
            onClick={() => addItem("Eggs (6pc)", 60)}
            className="px-2 py-1 bg-gray-100 rounded"
          >
            + Eggs
          </button>
        </div>
      </div>
    </div>
  );
}
