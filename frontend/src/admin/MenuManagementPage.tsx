/**
 * Menu Management — CRUD categories & items, toggle availability/active.
 */

import { useState, useEffect, useCallback } from "react";
import { useAdminAuth } from "./AdminAuthContext";
import {
  listCategories,
  createCategory,
  updateCategory,
  listMenuItems,
  createMenuItem,
  updateMenuItem,
  getPrepTimePresets,
} from "./api";
import type { MenuCategory, MenuItem, PrepTimePresets } from "./types";

export default function MenuManagementPage() {
  const { token } = useAdminAuth();
  const [categories, setCategories] = useState<MenuCategory[]>([]);
  const [items, setItems] = useState<MenuItem[]>([]);
  const [presets, setPresets] = useState<PrepTimePresets | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Category form
  const [showCatForm, setShowCatForm] = useState(false);
  const [editingCat, setEditingCat] = useState<MenuCategory | null>(null);
  const [catName, setCatName] = useState("");
  const [catSort, setCatSort] = useState(0);

  // Item form
  const [showItemForm, setShowItemForm] = useState(false);
  const [editingItem, setEditingItem] = useState<MenuItem | null>(null);
  const [itemName, setItemName] = useState("");
  const [itemPrice, setItemPrice] = useState("");
  const [itemPrepTime, setItemPrepTime] = useState("");
  const [itemCategoryId, setItemCategoryId] = useState("");
  const [itemDescription, setItemDescription] = useState("");
  const [itemImageUrl, setItemImageUrl] = useState("");
  const [itemSort, setItemSort] = useState("");

  const loadData = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const [cats, menuItems, p] = await Promise.all([
        listCategories(token),
        listMenuItems(token),
        getPrepTimePresets(token).catch(() => null),
      ]);
      setCategories(cats);
      setItems(menuItems);
      setPresets(p);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi tải dữ liệu");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // --- Category handlers ---

  const openCatForm = (cat?: MenuCategory) => {
    if (cat) {
      setEditingCat(cat);
      setCatName(cat.name);
      setCatSort(cat.sort_order);
    } else {
      setEditingCat(null);
      setCatName("");
      setCatSort(categories.length);
    }
    setShowCatForm(true);
  };

  const handleCatSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !catName.trim()) return;
    try {
      if (editingCat) {
        await updateCategory(token, editingCat.id, {
          name: catName.trim(),
          sort_order: catSort,
        });
      } else {
        await createCategory(token, { name: catName.trim(), sort_order: catSort });
      }
      setShowCatForm(false);
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi lưu nhóm");
    }
  };

  const toggleCatActive = async (cat: MenuCategory) => {
    if (!token) return;
    try {
      await updateCategory(token, cat.id, { is_active: !cat.is_active });
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi cập nhật");
    }
  };

  // --- Item handlers ---

  const openItemForm = (item?: MenuItem) => {
    if (item) {
      setEditingItem(item);
      setItemName(item.name);
      setItemPrice(item.price);
      setItemPrepTime(String(item.prep_time_minutes));
      setItemCategoryId(item.category_id || "");
      setItemDescription(item.description || "");
      setItemImageUrl(item.image_url || "");
      setItemSort(String(item.sort_order));
    } else {
      setEditingItem(null);
      setItemName("");
      setItemPrice("");
      setItemPrepTime("");
      setItemCategoryId("");
      setItemDescription("");
      setItemImageUrl("");
      setItemSort("");
    }
    setShowItemForm(true);
  };

  const applyPreset = (type: "savory" | "light") => {
    if (!presets) return;
    setItemPrepTime(
      String(
        type === "savory"
          ? presets.default_savory_minutes
          : presets.default_light_minutes
      )
    );
  };

  const handleItemSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !itemName.trim() || !itemPrice) return;
    const data = {
      name: itemName.trim(),
      price: parseFloat(itemPrice),
      prep_time_minutes: parseInt(itemPrepTime) || 10,
      category_id: itemCategoryId || undefined,
      description: itemDescription || undefined,
      image_url: itemImageUrl || undefined,
      sort_order: itemSort ? parseInt(itemSort) : undefined,
    };
    try {
      if (editingItem) {
        await updateMenuItem(token, editingItem.id, data);
      } else {
        await createMenuItem(token, data);
      }
      setShowItemForm(false);
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi lưu món");
    }
  };

  const toggleItemAvailable = async (item: MenuItem) => {
    if (!token) return;
    try {
      await updateMenuItem(token, item.id, { is_available: !item.is_available });
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi cập nhật");
    }
  };

  const toggleItemActive = async (item: MenuItem) => {
    if (!token) return;
    try {
      await updateMenuItem(token, item.id, { is_active: !item.is_active });
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi cập nhật");
    }
  };

  if (loading) {
    return <div className="text-gray-500">Đang tải...</div>;
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-gray-800">Quản lý Menu</h1>

      {error && (
        <div className="bg-red-50 text-red-600 px-4 py-2 rounded-lg">
          {error}
        </div>
      )}

      {/* Categories Section */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-700">Nhóm món</h2>
          <button
            onClick={() => openCatForm()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm"
          >
            + Thêm nhóm
          </button>
        </div>

        {showCatForm && (
          <form
            onSubmit={handleCatSubmit}
            className="bg-white p-4 rounded-lg shadow mb-4 flex gap-3 items-end"
          >
            <div className="flex-1">
              <label className="block text-sm text-gray-600 mb-1">Tên nhóm</label>
              <input
                type="text"
                value={catName}
                onChange={(e) => setCatName(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                autoFocus
              />
            </div>
            <div className="w-24">
              <label className="block text-sm text-gray-600 mb-1">Thứ tự</label>
              <input
                type="number"
                value={catSort}
                onChange={(e) => setCatSort(parseInt(e.target.value) || 0)}
                className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <button
              type="submit"
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700"
            >
              {editingCat ? "Cập nhật" : "Tạo"}
            </button>
            <button
              type="button"
              onClick={() => setShowCatForm(false)}
              className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
            >
              Huỷ
            </button>
          </form>
        )}

        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-3 text-gray-600">Tên</th>
                <th className="text-left px-4 py-3 text-gray-600">Thứ tự</th>
                <th className="text-left px-4 py-3 text-gray-600">Trạng thái</th>
                <th className="text-right px-4 py-3 text-gray-600">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {categories.map((cat) => (
                <tr key={cat.id}>
                  <td className="px-4 py-3">{cat.name}</td>
                  <td className="px-4 py-3">{cat.sort_order}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-1 rounded text-xs ${
                        cat.is_active
                          ? "bg-green-100 text-green-700"
                          : "bg-red-100 text-red-700"
                      }`}
                    >
                      {cat.is_active ? "Hoạt động" : "Ẩn"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right space-x-2">
                    <button
                      onClick={() => openCatForm(cat)}
                      className="text-blue-600 hover:underline"
                    >
                      Sửa
                    </button>
                    <button
                      onClick={() => toggleCatActive(cat)}
                      className="text-orange-600 hover:underline"
                    >
                      {cat.is_active ? "Ẩn" : "Hiện"}
                    </button>
                  </td>
                </tr>
              ))}
              {categories.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-gray-400">
                    Chưa có nhóm nào
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Menu Items Section */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-700">Danh sách món</h2>
          <button
            onClick={() => openItemForm()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm"
          >
            + Thêm món
          </button>
        </div>

        {showItemForm && (
          <form
            onSubmit={handleItemSubmit}
            className="bg-white p-4 rounded-lg shadow mb-4 space-y-3"
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="block text-sm text-gray-600 mb-1">Tên món *</label>
                <input
                  type="text"
                  value={itemName}
                  onChange={(e) => setItemName(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">Giá *</label>
                <input
                  type="number"
                  value={itemPrice}
                  onChange={(e) => setItemPrice(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  step="1000"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">
                  Thời gian chế biến (phút) *
                </label>
                <div className="flex gap-2">
                  <input
                    type="number"
                    value={itemPrepTime}
                    onChange={(e) => setItemPrepTime(e.target.value)}
                    className="flex-1 px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  {presets && (
                    <div className="flex gap-1">
                      <button
                        type="button"
                        onClick={() => applyPreset("savory")}
                        className="px-2 py-1 bg-orange-100 text-orange-700 rounded text-xs hover:bg-orange-200"
                        title={`Mặn: ${presets.default_savory_minutes} phút`}
                      >
                        Mặn
                      </button>
                      <button
                        type="button"
                        onClick={() => applyPreset("light")}
                        className="px-2 py-1 bg-green-100 text-green-700 rounded text-xs hover:bg-green-200"
                        title={`Nhẹ: ${presets.default_light_minutes} phút`}
                      >
                        Nhẹ
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="block text-sm text-gray-600 mb-1">Nhóm</label>
                <select
                  value={itemCategoryId}
                  onChange={(e) => setItemCategoryId(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">-- Không --</option>
                  {categories
                    .filter((c) => c.is_active)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">URL ảnh</label>
                <input
                  type="text"
                  value={itemImageUrl}
                  onChange={(e) => setItemImageUrl(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="https://..."
                />
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">Thứ tự</label>
                <input
                  type="number"
                  value={itemSort}
                  onChange={(e) => setItemSort(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm text-gray-600 mb-1">Mô tả</label>
              <textarea
                value={itemDescription}
                onChange={(e) => setItemDescription(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={2}
              />
            </div>

            <div className="flex gap-2">
              <button
                type="submit"
                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700"
              >
                {editingItem ? "Cập nhật" : "Tạo món"}
              </button>
              <button
                type="button"
                onClick={() => setShowItemForm(false)}
                className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
              >
                Huỷ
              </button>
            </div>
          </form>
        )}

        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-3 text-gray-600">Tên</th>
                <th className="text-left px-4 py-3 text-gray-600">Giá</th>
                <th className="text-left px-4 py-3 text-gray-600">Nhóm</th>
                <th className="text-left px-4 py-3 text-gray-600">Có sẵn</th>
                <th className="text-left px-4 py-3 text-gray-600">Trạng thái</th>
                <th className="text-right px-4 py-3 text-gray-600">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((item) => {
                const cat = categories.find((c) => c.id === item.category_id);
                return (
                  <tr key={item.id}>
                    <td className="px-4 py-3 font-medium">{item.name}</td>
                    <td className="px-4 py-3">{item.price}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {cat?.name || "—"}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => toggleItemAvailable(item)}
                        className={`px-2 py-1 rounded text-xs ${
                          item.is_available
                            ? "bg-green-100 text-green-700"
                            : "bg-yellow-100 text-yellow-700"
                        }`}
                      >
                        {item.is_available ? "Có" : "Hết"}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-1 rounded text-xs ${
                          item.is_active
                            ? "bg-green-100 text-green-700"
                            : "bg-red-100 text-red-700"
                        }`}
                      >
                        {item.is_active ? "Hoạt động" : "Ẩn"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right space-x-2">
                      <button
                        onClick={() => openItemForm(item)}
                        className="text-blue-600 hover:underline"
                      >
                        Sửa
                      </button>
                      <button
                        onClick={() => toggleItemActive(item)}
                        className="text-orange-600 hover:underline"
                      >
                        {item.is_active ? "Ẩn" : "Hiện"}
                      </button>
                    </td>
                  </tr>
                );
              })}
              {items.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-gray-400">
                    Chưa có món nào
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
