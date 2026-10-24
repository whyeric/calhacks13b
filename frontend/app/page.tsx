import { API_URL } from "@/lib/api";

export default function Home() {
  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-semibold">Hedge Desk</h1>
      <p className="mt-2 text-sm text-neutral-500">Dashboard coming soon. API: {API_URL}</p>
    </main>
  );
}
