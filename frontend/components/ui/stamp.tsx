import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

// A rubber stamp: shadcn's Badge recut for the blotter. Renders a <span> so it
// can sit inside a paragraph. Ink color carries the meaning; the tilt is decoration.
const stampVariants = cva(
  "stamp inline-flex items-center gap-1 whitespace-nowrap border-2 bg-transparent px-1.5 py-px font-mono text-[11px] font-medium uppercase leading-4 tracking-[0.08em]",
  {
    variants: {
      ink: {
        green: "stamp-green",
        red: "stamp-red",
        amber: "stamp-amber",
        violet: "stamp-violet",
        blue: "stamp-blue",
        pencil: "stamp-pencil",
      },
      tilt: {
        none: "",
        left: "-rotate-2",
        right: "rotate-1",
      },
    },
    defaultVariants: { ink: "pencil", tilt: "none" },
  },
);

export interface StampProps
  extends
    React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof stampVariants> {}

function Stamp({ className, ink, tilt, ...props }: StampProps) {
  return (
    <span className={cn(stampVariants({ ink, tilt }), className)} {...props} />
  );
}

export { Stamp, stampVariants };
