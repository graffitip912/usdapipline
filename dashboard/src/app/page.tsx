import Link from "next/link";

export default function HomePage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">USDA Grain Pipeline Dashboard</h1>
        <p className="mt-2 text-gray-600">
          CBOT grain data collection, analysis, and satellite/weather image viewer.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Link
          href="/grain"
          className="block p-6 bg-white rounded-lg border border-gray-200 shadow-sm hover:shadow-md transition-shadow"
        >
          <h2 className="text-xl font-semibold text-gray-900">Grain Analysis</h2>
          <p className="mt-2 text-sm text-gray-600">
            Corn, soybeans, wheat price trends, supply/demand charts, and GTR transportation indices.
          </p>
        </Link>

        <Link
          href="/images"
          className="block p-6 bg-white rounded-lg border border-gray-200 shadow-sm hover:shadow-md transition-shadow"
        >
          <h2 className="text-xl font-semibold text-gray-900">Image Viewer</h2>
          <p className="mt-2 text-sm text-gray-600">
            WWCB satellite/weather images with description text, region filtering, and metadata.
          </p>
        </Link>

        <Link
          href="/admin"
          className="block p-6 bg-white rounded-lg border border-gray-200 shadow-sm hover:shadow-md transition-shadow"
        >
          <h2 className="text-xl font-semibold text-gray-900">Admin Monitor</h2>
          <p className="mt-2 text-sm text-gray-600">
            Collection status, schedule management, and manual collection triggers.
          </p>
        </Link>
      </div>
    </div>
  );
}
