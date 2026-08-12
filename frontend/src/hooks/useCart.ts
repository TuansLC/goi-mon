import { useState, useCallback } from "react";
import type { CartItem, MenuItem } from "../types";

export function useCart() {
  const [items, setItems] = useState<CartItem[]>([]);

  const addItem = useCallback((menuItem: MenuItem) => {
    setItems((prev) => {
      const existing = prev.find((i) => i.menu_item_id === menuItem.id);
      if (existing) {
        return prev.map((i) =>
          i.menu_item_id === menuItem.id
            ? { ...i, quantity: i.quantity + 1 }
            : i
        );
      }
      return [
        ...prev,
        {
          menu_item_id: menuItem.id,
          name: menuItem.name,
          price: parseFloat(menuItem.price),
          quantity: 1,
          note: "",
        },
      ];
    });
  }, []);

  const removeItem = useCallback((menuItemId: string) => {
    setItems((prev) => prev.filter((i) => i.menu_item_id !== menuItemId));
  }, []);

  const updateQuantity = useCallback((menuItemId: string, quantity: number) => {
    if (quantity <= 0) {
      setItems((prev) => prev.filter((i) => i.menu_item_id !== menuItemId));
      return;
    }
    setItems((prev) =>
      prev.map((i) =>
        i.menu_item_id === menuItemId ? { ...i, quantity } : i
      )
    );
  }, []);

  const updateNote = useCallback((menuItemId: string, note: string) => {
    setItems((prev) =>
      prev.map((i) =>
        i.menu_item_id === menuItemId ? { ...i, note } : i
      )
    );
  }, []);

  const clearCart = useCallback(() => {
    setItems([]);
  }, []);

  const totalAmount = items.reduce(
    (sum, item) => sum + item.price * item.quantity,
    0
  );

  const totalItems = items.reduce((sum, item) => sum + item.quantity, 0);

  return {
    items,
    addItem,
    removeItem,
    updateQuantity,
    updateNote,
    clearCart,
    totalAmount,
    totalItems,
  };
}
