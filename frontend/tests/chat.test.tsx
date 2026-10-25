import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ChatDrawer } from "@/components/ChatDrawer";
import reply from "@/fixtures/chat_reply.json";
const api = "http://localhost:8000";
let body: unknown;
const server = setupServer(
  http.post(`${api}/businesses/:id/chat`, async ({ request }) => {
    body = await request.json();
    return HttpResponse.json(reply);
  }),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
const mount = () =>
  render(<ChatDrawer businessId="restaurant" open onClose={() => {}} />);
function ask(text: string) {
  fireEvent.change(screen.getByLabelText("Your question"), {
    target: { value: text },
  });
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
}

describe("C7-A29 chat drawer", () => {
  it("echoes the question and renders the reply text untouched", async () => {
    mount();
    ask("Why?");
    expect(
      within(screen.getByTestId("chat-owner")).getByText("Why?"),
    ).toBeVisible();
    const desk = await screen.findByTestId("chat-desk");
    // Numbers stay exactly as the API wrote them (62¢, 27%, 35¢).
    expect(within(desk).getByText(reply.reply)).toBeVisible();
    expect(body).toEqual({ message: "Why?" });
    expect(screen.getByLabelText("Your question")).toHaveValue("");
  });
  it("tool calls are expandable with input and output", async () => {
    mount();
    ask("Why?");
    const desk = await screen.findByTestId("chat-desk");
    const details = desk.querySelector("details.tool-call")!;
    expect(details).not.toHaveAttribute("open");
    expect(within(desk).getByText("read_log")).toBeVisible();
    fireEvent.click(within(desk).getByText(/Looked up/));
    expect(details).toHaveAttribute("open");
    expect(details.textContent).toContain('"hedge_id": "hdg_03"');
    expect(details.textContent).toContain('"overpay": "0.35"');
  });
  it("keeps the typed question when the request fails", async () => {
    server.use(
      http.post(`${api}/businesses/:id/chat`, () =>
        HttpResponse.json(
          {
            error: {
              code: "bad",
              message: "Chat is unavailable.",
              detail: null,
            },
          },
          { status: 503 },
        ),
      ),
    );
    mount();
    ask("Why was rain declined?");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Chat is unavailable.",
    );
    expect(screen.getByLabelText("Your question")).toHaveValue(
      "Why was rain declined?",
    );
  });
});
