import * as React from "react";

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-xl border text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 ring-offset-page",
  {
    variants: {
      variant: {
        default: "border-transparent bg-accent px-3 py-2 text-white hover:bg-[var(--accent-700)]",
        secondary: "border-border bg-raised px-3 py-2 text-primary hover:bg-hover",
        ghost: "border-transparent bg-transparent px-3 py-2 text-secondary hover:bg-hover hover:text-primary",
        danger: "border-transparent bg-danger px-3 py-2 text-white hover:bg-[color:color-mix(in_srgb,var(--danger)_88%,black)]",
      },
      size: {
        default: "h-10",
        sm: "h-8 rounded-lg px-3 text-[13px]",
        lg: "h-11 px-5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
