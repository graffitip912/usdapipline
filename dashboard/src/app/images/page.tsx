"use client";

import { useEffect, useState } from "react";
import { getImages, getImageMeta, imageFileUrl, type ImageItem, type ImageMeta } from "@/lib/api";

export default function ImagesPage() {
  const [images, setImages] = useState<ImageItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedMeta, setSelectedMeta] = useState<ImageMeta | null>(null);
  const [regionFilter, setRegionFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");

  useEffect(() => {
    setLoading(true);
    getImages({
      region: regionFilter || undefined,
      category: categoryFilter || undefined,
    })
      .then(setImages)
      .catch(() => setImages([]))
      .finally(() => setLoading(false));
  }, [regionFilter, categoryFilter]);

  useEffect(() => {
    if (!selectedId) {
      setSelectedMeta(null);
      return;
    }
    getImageMeta(selectedId)
      .then(setSelectedMeta)
      .catch(() => setSelectedMeta(null));
  }, [selectedId]);

  const regions = [...new Set(images.map((i) => i.region).filter(Boolean))].sort();
  const categories = [...new Set(images.map((i) => i.category).filter(Boolean))].sort();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <h1 className="text-2xl font-bold text-gray-900">WWCB Image Viewer</h1>
        <div className="flex gap-2">
          <select
            value={regionFilter}
            onChange={(e) => setRegionFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm bg-white"
          >
            <option value="">All Regions</option>
            {regions.map((r) => (
              <option key={r} value={r!}>{r}</option>
            ))}
          </select>
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm bg-white"
          >
            <option value="">All Categories</option>
            {categories.map((c) => (
              <option key={c} value={c!}>{c}</option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading images...</div>
      ) : images.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          No images found. Run the WWCB image collector first.
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
          {images.map((img) => (
            <button
              key={img.id}
              onClick={() => setSelectedId(img.id)}
              className="bg-white rounded-lg border border-gray-200 overflow-hidden hover:shadow-md transition-shadow text-left"
            >
              <div className="aspect-square bg-gray-100 flex items-center justify-center overflow-hidden">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={imageFileUrl(img.id)}
                  alt={img.filename}
                  className="w-full h-full object-cover"
                  loading="lazy"
                />
              </div>
              <div className="p-2">
                <p className="text-xs font-medium text-gray-700 truncate">{img.pdf_date}</p>
                <p className="text-xs text-gray-500 truncate">{img.region || "Unknown"}</p>
                <span className="inline-block mt-1 px-1.5 py-0.5 text-xs rounded bg-blue-50 text-blue-700">
                  {img.category}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}

      {selectedId && selectedMeta && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50"
          onClick={() => setSelectedId(null)}
        >
          <div
            className="bg-white rounded-lg max-w-4xl w-full max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-4 border-b flex justify-between items-center">
              <h2 className="text-lg font-semibold">{selectedMeta.filename}</h2>
              <button
                onClick={() => setSelectedId(null)}
                className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
              >
                &times;
              </button>
            </div>
            <div className="p-4 grid md:grid-cols-2 gap-4">
              <div>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={imageFileUrl(selectedId)}
                  alt={selectedMeta.filename}
                  className="w-full rounded"
                />
              </div>
              <div className="space-y-3 text-sm">
                <div>
                  <span className="font-medium text-gray-700">Date:</span>{" "}
                  <span>{selectedMeta.pdf_date}</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">Region:</span>{" "}
                  <span>{selectedMeta.region || "Unknown"}</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">Category:</span>{" "}
                  <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700">{selectedMeta.category}</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">Size:</span>{" "}
                  <span>{selectedMeta.width}x{selectedMeta.height}</span>
                </div>
                {selectedMeta.section_header && (
                  <div>
                    <span className="font-medium text-gray-700">Section:</span>{" "}
                    <span>{selectedMeta.section_header}</span>
                  </div>
                )}
                {selectedMeta.page_text && (
                  <div>
                    <span className="font-medium text-gray-700">Description:</span>
                    <p className="mt-1 text-gray-600 whitespace-pre-line max-h-48 overflow-y-auto">
                      {selectedMeta.page_text}
                    </p>
                  </div>
                )}
                {selectedMeta.ocr_text && (
                  <div>
                    <span className="font-medium text-gray-700">OCR Text:</span>
                    <p className="mt-1 text-gray-600 whitespace-pre-line max-h-32 overflow-y-auto">
                      {selectedMeta.ocr_text}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
